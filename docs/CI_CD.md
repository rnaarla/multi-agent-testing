# CI/CD requirements and behavior

This document describes **what GitHub Actions enforces today**, how jobs depend on each other, and what maintainers must satisfy when changing the API or tooling. It also summarizes **compliance-oriented capabilities** that this pipeline can support for regulated-industry programs (see **§11**—not a substitute for legal or production-only controls).

Workflow file: [`.github/workflows/ci.yaml`](../.github/workflows/ci.yaml).

---

## 1. When CI runs

| Event | Branches |
| ----- | -------- |
| `push` | `main`, `master`, `develop` |
| `pull_request` | `main`, `master` |

**Implication:** Pushes to other branches do **not** run this workflow unless you extend `on:`.

---

## 2. Job graph (dependencies)

```
backend-test ──┬──► integration-test ──► build-images ──► deploy
frontend-test ─┘         ▲
                           │
              (only if push ref is refs/heads/main)

security-scan  (no `needs`; runs in parallel with other jobs)
```

| Job | Needs | Purpose |
| --- | ----- | ------- |
| **backend-test** | — | Python lint (scoped), typecheck (scoped), pytest + coverage, Codecov upload |
| **frontend-test** | — | `npm ci` (fallback `npm install`), ESLint, production build |
| **integration-test** | `backend-test`, `frontend-test` | Docker Compose build/up, health + curl smoke |
| **security-scan** | — | Trivy filesystem scan → SARIF → CodeQL upload |
| **build-images** | `integration-test` | Build and push backend + frontend images to GHCR |
| **deploy** | `build-images` | Placeholder echo (no real deploy) |

---

## 3. Branch conditions (important)

| Job | Runs when |
| --- | ----------- |
| **build-images** | `github.ref == 'refs/heads/main'` **only** |
| **deploy** | `github.ref == 'refs/heads/main'` **only** |

So:

- **`master` and `develop` get full CI** (tests, lint, integration, security scan).
- **Image build + deploy job only run on `main`**, not on `master`/`develop`, unless you change the `if:` filters.

If your default branch is `master` and you expect images on every green build, either merge to `main` or align the `if:` with your default branch.

---

## 4. Backend job (`backend-test`)

### 4.1 Services

- **PostgreSQL 15** — `POSTGRES_DB=agent_tests_test`, port `5432`, health `pg_isready`.
- **Redis 7** — port `6379`, health `redis-cli ping`.

### 4.2 Environment for tests

| Variable | Value |
| -------- | ----- |
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/agent_tests_test` |
| `REDIS_URL` | `redis://localhost:6379/0` |
| `JWT_SECRET` | `test-secret-key` |

### 4.3 Toolchain

- **Python:** `3.11` (`PYTHON_VERSION` in workflow).
- **Dependencies:** `pip install -r backend/requirements.txt` (pip cache keyed on that file).

### 4.4 Lint — Ruff (incremental gate)

- **Not** the whole `src/app` tree (that would surface legacy debt in one step).
- Runs [`backend/scripts/ruff_critical.sh`](../backend/scripts/ruff_critical.sh):
  - `src/app/simulation/`
  - `src/app/services/simulation_service.py`
  - `src/app/routers/simulation.py`

**Requirement:** Changes under those paths must pass Ruff.

### 4.5 Type check — MyPy (incremental gate)

- Runs [`backend/scripts/mypy_critical.sh`](../backend/scripts/mypy_critical.sh):
  - Same file set as Ruff critical script (simulation + simulation router/service).
- Flags: `--follow-imports=skip --ignore-missing-imports` so the gate is **local** to those modules.

**Requirement:** Those files must typecheck under this configuration. Expanding coverage is optional: extend the script and fix issues incrementally.

### 4.6 Tests and coverage

- **Working directory:** `backend/`.
- **Command:** `pytest -v --cov=app --cov-report=xml`.
- **Discovery:** [`backend/pytest.ini`](../backend/pytest.ini) sets `pythonpath = src` and `testpaths = tests` — the suite is **`backend/tests/`**, not `app/`.

**Coverage configuration:** [`backend/.coveragerc`](../backend/.coveragerc)

- **`[run] omit`:** Large subtrees are excluded from coverage *measurement* (auth, governance, providers, routers, runner, workers, `models_enhanced.py`). That keeps the number focused on much of the core app under test.
- **`[report] fail_under`:** Currently **83** — CI fails if total measured coverage drops below this. Raise it only when the suite and omits still justify a higher bar.

### 4.7 Codecov

- Uploads `backend/coverage.xml` with flag `backend`.
- **Private repos** often need a `CODECOV_TOKEN` repository secret; without it, upload may warn or fail non-fatally depending on Codecov settings.

---

## 5. Frontend job (`frontend-test`)

### 5.1 Toolchain

- **Node:** `20` (`NODE_VERSION`).
- **Cache:** npm cache keyed on `frontend/package-lock.json`.

### 5.2 Install

```bash
cd frontend && npm ci || npm install
```

`npm ci` is preferred for reproducible CI; `npm install` is a fallback if the lockfile is out of sync (should be rare).

### 5.3 Required commands

| Step | Command | Requirement |
| ---- | ------- | ------------- |
| Lint | `npm run lint` | **Must pass** (ESLint on `src/`, max warnings 0). |
| Build | `npm run build` | **Must pass** (Vite production build). |

There is **no** required `npm test` step in CI today.

---

## 6. Integration job (`integration-test`)

- **Needs:** both `backend-test` and `frontend-test` green.
- **Docker Compose:** `docker compose build`, then `docker compose up -d db redis backend`, sleep `10`, then:
  - `curl -f http://localhost:8000/health`
  - `POST /graphs` with a minimal JSON body (expect success)
  - `GET /graphs`
  - `GET /metrics/summary`
- **Cleanup:** `docker compose down -v` (always, `if: always()`).

**Requirement:** Compose service names and API routes used here must stay compatible, or this job must be updated.

**Note:** These checks are **unauthenticated** HTTP calls. If endpoints later require auth, this job must be updated (e.g. obtain a token or use internal health-only routes).

---

## 7. Security scan (`security-scan`)

- **Trivy** filesystem scan on repo root, SARIF output.
- **Upload:** `github/codeql-action/upload-sarif@v2`.

**Requirements / caveats:**

- Upload may require **GitHub Advanced Security** or appropriate permissions for private repos.
- Fork PRs from external contributors may fail SARIF upload; adjust workflow permissions or conditions if that becomes noisy.

This job has **no** `needs` dependency, so it runs **in parallel** with backend/frontend jobs.

---

## 8. Build and push (`build-images`)

- **Only on `refs/heads/main`** after `integration-test` succeeds.
- **GHCR:** `ghcr.io/<owner>/<repo>/backend:latest` and `.../frontend:latest`.
- Uses **Docker Buildx** and GHA cache.

**Requirement:** `GITHUB_TOKEN` must have permission to push packages (default for same-repo workflows is usually sufficient).

---

## 9. Deploy (`deploy`)

- **Only on `main`**, after `build-images`.
- Uses GitHub **environment** `production`.
- Currently **placeholder only** (`echo`); no cluster or compose deploy is performed.

---

## 10. API contract (OpenAPI)

- Canonical snapshot: **`backend/docs/openapi-schema.json`**.
- Regenerate after intentional API changes:

```bash
cd backend
python scripts/generate_openapi.py
```

- **CI enforcement:** `tests/test_openapi_schema.py` compares stored vs generated OpenAPI **paths** (excluding `/__test*`). **Drift fails the build**; it does **not** auto-update the JSON file in CI.

---

## 11. Compliance-oriented capabilities (what this pipeline can support)

This workflow is **not** a substitute for legal agreements, formal risk analysis, or production-only controls. It **is** a practical layer auditors and security teams often map to **secure SDLC**, **change management**, and **vulnerability management** themes common across regulated sectors.

### 11.1 Capabilities this repo’s CI/CD already contributes

| Capability | How this pipeline supports it | Typical audit / control mapping (illustrative) |
| ---------- | ------------------------------ | ---------------------------------------------- |
| **Change & release discipline** | Every merge to gated branches runs automated checks before integration/deploy jobs; Git history + Actions run IDs provide **who changed what, when, with what result**. | SOC 2 **CC8** (change management); ISO 27001 **A.12.1** (operating procedures). |
| **Automated security testing (baseline)** | **Trivy** filesystem scan + SARIF upload; scoped **Ruff** / **MyPy** on critical paths; **pytest** including tenant-isolation style tests. | SOC 2 **CC7** (vulnerability / monitoring); HIPAA **§164.308(a)(1)(ii)(B)** (protection against malicious software) as one *technical* input—not the whole safeguard. |
| **Functional / correctness regression** | Backend test suite + coverage floor; **OpenAPI drift** gate reduces accidental API breakage that could affect clients handling sensitive workflows. | Supports **integrity** and **availability** narratives when tied to risk assessment. |
| **Build reproducibility & provenance (partial)** | **Docker Buildx** builds images on `main` after tests; tags point at a **known commit**. (Signing / SBOM / SLSA attestations are **not** in this file yet—extend if required.) | PCI DSS **6** (secure systems); customer due-diligence on supply chain. |
| **Frontend integrity** | **Lint + production build** catch whole classes of defects before release. | General product quality; supports change-control evidence. |

### 11.2 Regulated industries — how teams usually use CI/CD *alongside* other evidence

| Sector | CI/CD is strong evidence for… | Still required outside CI (examples) |
| ------ | ------------------------------ | -------------------------------------- |
| **Healthcare (e.g. HIPAA)** | Technical safeguards implemented in code (access patterns, tests), change control for software, vulnerability scanning artifacts. | BAA, workforce training, risk analysis, **production** audit logs & retention, breach process, physical/administrative safeguards. |
| **Finance (e.g. SOC 2, PCI if in scope)** | CC6/CC7/CC8-style narratives for logical access, monitoring, and change management when PR + CI + protected branches are documented. | Access reviews, vendor management, **production** logging/monitoring, incident response; PCI network segmentation and ASV scans if handling card data. |
| **Other regulated contexts (GDPR, GLBA, etc.)** | Demonstrating **secure development** and **documented release process** for processing systems. | Lawful basis, DPIA, data subject rights procedures, DPA, cross-border transfer mechanisms—**legal / process**, not pytest. |

### 11.3 Explicit non-claims

- This document does **not** state that running this workflow makes the product **HIPAA-compliant**, **SOC 2 certified**, **PCI DSS validated**, or equivalent.
- **Production** controls (encryption at rest in live DBs, KMS policies, backup/DR drills, SIEM retention, pen tests) are **orthogonal** to this YAML; reference your environment’s runbooks and GRC system for those.

### 11.4 Extending the pipeline for stronger compliance evidence

When your GRC program requires it, common additions include: **dependency review / Dependabot with SLAs**, **secret scanning** on PRs, **SAST** (e.g. CodeQL), **SBOM** per image, **signed containers**, **IaC policy** (OPA/Conftest), **branch protection + required reviewers**, and **immutable artifact retention** aligned to your retention policy.

---

## 12. Maintainer checklist (PR readiness)

1. `cd backend && ./scripts/ruff_critical.sh && ./scripts/mypy_critical.sh && pytest -v --cov=app`
2. `cd frontend && npm ci && npm run lint && npm run build`
3. If HTTP routes changed: `python scripts/generate_openapi.py` and commit `docs/openapi-schema.json`
4. If coverage drops below `fail_under` in `.coveragerc`: add tests or adjust omits/floor with team agreement
5. If default branch is not `main` but you need GHCR images: align `build-images` / `deploy` `if:` conditions

---

## 13. Known gaps (honest)

- **MyPy / Ruff** are **scoped**, not repo-wide.
- **Codecov** may need configuration for private repositories.
- **Integration** smoke does not run the full pytest suite inside Compose; it only validates a running stack + a few endpoints.
- **`deploy`** is a stub; production delivery is out of band unless you replace that step.

For product-level “shipped vs roadmap,” see the table in the root [README](../README.md).
