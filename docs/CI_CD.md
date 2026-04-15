# CI/CD requirements and behavior

This document describes **what GitHub Actions enforces today**, how jobs depend on each other, and what maintainers must satisfy when changing the API or tooling. It also summarizes **compliance-oriented capabilities** that this pipeline can support for regulated-industry programs (see **§12**—not a substitute for legal or production-only controls).

Workflow files:

- Primary pipeline: [`.github/workflows/ci.yaml`](../.github/workflows/ci.yaml)
- SAST (scheduled + same branches as CI): [`.github/workflows/codeql.yml`](../.github/workflows/codeql.yml)
- Dependency PRs: [`.github/dependabot.yml`](../.github/dependabot.yml)

**Operational defaults (repo policy):** workflow-level **`permissions: contents: read`**, **`concurrency`** with `cancel-in-progress: true` (dedupe superseded runs), per-job **`timeout-minutes`**, **`workflow_dispatch`** for safe reruns, **pinned** third-party action minors where practical (Trivy, TruffleHog CLI version), and **least-privilege** job permissions where a job needs more than `contents: read`.

---

## 1. When CI runs

| Event | Branches |
| ----- | -------- |
| `push` | `main`, `master`, `develop` |
| `pull_request` | `main`, `master` |
| `workflow_dispatch` | Same workflow file; branch at run time |

**Implication:** Pushes to other branches do **not** run this workflow unless you extend `on:`.

---

## 2. Job graph (dependencies)

```
backend-test ──┬──► integration-test ──► build-images ──┬──► deploy
frontend-test ─┘                                       └──► sbom-artifacts

dependency-review (pull_request only; parallel)
secret-scan         (parallel; fork PRs skipped — see §7)
security-scan       (parallel; Trivy FS → SARIF)
```

**Separate workflow:** `codeql.yml` runs **CodeQL** for Python (`backend/src`) and JavaScript (`frontend/src`) on the same branch triggers plus a **weekly** schedule. Python extraction uses **`pip install -r backend/requirements.txt`** plus **`python -m compileall backend/src`** (no repo-root autobuild). JavaScript uses **`npm ci`** under `frontend/`. It does not gate `integration-test` in YAML; treat it as a **required check** in branch protection if you want merges blocked on SAST.

| Job | Needs | Purpose |
| --- | ----- | ------- |
| **backend-test** | — | Ruff/MyPy (critical paths), pytest + coverage, Codecov upload (non-blocking on upload errors) |
| **frontend-test** | — | `npm ci` (fallback `npm install`), ESLint, production build |
| **dependency-review** | — | **PRs only** — GitHub **Dependency review** (fail on **high**+ severity by default) |
| **integration-test** | `backend-test`, `frontend-test` | Docker Compose build/up, health + curl smoke |
| **security-scan** | — | **Trivy** filesystem scan (pinned action) → SARIF → CodeQL **upload-sarif** |
| **secret-scan** | — | **TruffleHog** git scan (pinned CLI via action), `--only-verified`; **skipped** for pull requests from forks |
| **build-images** | `integration-test` | Build/push backend + frontend to GHCR (**default branch** only); Buildx **provenance** + **SBOM** attestations |
| **sbom-artifacts** | `build-images` | **Trivy** CycloneDX SBOM for each pushed image → **workflow artifacts** (90-day retention) |
| **deploy** | `build-images` | Placeholder echo (no real deploy) |

---

## 3. Branch conditions (important)

| Job | Runs when |
| --- | ----------- |
| **build-images** | `github.ref == refs/heads/<repository.default_branch>` **only** |
| **sbom-artifacts** | Same as **build-images** (after images exist) |
| **deploy** | Same as **build-images** |

So:

- **`master` and `develop` get full test/lint/integration/security/secret/CodeQL coverage** when they are not the default branch (images are **not** built on those branches unless one of them is the repo default).
- **Image build, SBOM artifacts, and deploy** track **`github.event.repository.default_branch`** automatically—no hard-coded `main` in `if:` filters.

If you rename the default branch, update **branch protection** required checks and any external deploy triggers accordingly.

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

- Uses **`codecov/codecov-action@v4`** with optional `CODECOV_TOKEN` secret.
- **`fail_ci_if_error: false`** and **`continue-on-error: true`** on the step so flaky or misconfigured uploads do not fail the primary signal (pytest + coverage XML still fail locally/CI if you add a separate check).

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
  - `curl -fsS http://localhost:8000/health`
  - `POST /graphs` with a minimal JSON body (`curl -fsS -X POST ...`)
  - `GET /graphs`
  - `GET /metrics/summary`
- **Cleanup:** `docker compose down -v` (always, `if: always()`).

**Requirement:** Compose service names and API routes used here must stay compatible, or this job must be updated.

**Note:** These checks are **unauthenticated** HTTP calls. If endpoints later require auth, this job must be updated (e.g. obtain a token or use internal health-only routes).

---

## 7. Security scan (`security-scan`)

- **Trivy** filesystem scan on repo root, SARIF output (**`aquasecurity/trivy-action@v0.35.0`**, not a floating `@master` ref).
- **Upload:** `github/codeql-action/upload-sarif@v3` with job permissions `security-events: write`.

### 7.1 Secret scan (`secret-scan`)

- **TruffleHog** (`trufflesecurity/trufflehog` action, **pinned** release; CLI image version pinned via action input) with **`--results=verified`** (CLI v3+; avoids deprecated `--only-verified`).
- **Fork PRs:** job is **skipped** when `github.event.pull_request.head.repo.full_name != github.repository` so untrusted forks are not scanned under the same policy as trusted PRs (adjust if you use a different fork strategy).

**Requirements / caveats (Trivy SARIF):**

- Upload may require **GitHub Advanced Security** or appropriate permissions for private repos.
- Fork PRs from external contributors may fail SARIF upload; adjust workflow permissions or conditions if that becomes noisy.

---

## 8. Build and push (`build-images`)

- **Only on** `refs/heads/<default_branch>` after `integration-test` succeeds.
- **GHCR:** `ghcr.io/<owner>/<repo>/backend:latest` and `.../frontend:latest`.
- Uses **Docker Buildx** and GHA cache.
- **`provenance: mode=max`** and **`sbom: true`** on **`docker/build-push-action@v5`** for **in-registry** supply-chain attestations (complements downloadable CycloneDX in **§9**).

**Requirement:** `GITHUB_TOKEN` must have permission to push packages (`packages: write` on this job) and **`id-token: write`** for attestations.

---

## 9. SBOM artifacts (`sbom-artifacts`)

- Runs **after** `build-images` on the **default branch** only.
- Logs in to GHCR, runs **Trivy** in **`image`** mode with **`format: cyclonedx`**, uploads **`sbom-backend.cdx.json`** and **`sbom-frontend.cdx.json`** via **`actions/upload-artifact@v4`** with **`retention-days: 90`**.
- Intended for **audit / GRC evidence** and vulnerability diffing outside the registry.

---

## 10. Deploy (`deploy`)

- **Only on the default branch**, after `build-images`.
- Uses GitHub **environment** `production`.
- Currently **placeholder only** (`echo`); no cluster or compose deploy is performed.

---

## 11. API contract (OpenAPI)

- Canonical snapshot: **`backend/docs/openapi-schema.json`**.
- Regenerate after intentional API changes:

```bash
cd backend
python scripts/generate_openapi.py
```

- **CI enforcement:** `tests/test_openapi_schema.py` compares stored vs generated OpenAPI **paths** (excluding `/__test*`). **Drift fails the build**; it does **not** auto-update the JSON file in CI.

---

## 12. Compliance-oriented capabilities (what this pipeline can support)

This workflow is **not** a substitute for legal agreements, formal risk analysis, or production-only controls. It **is** a practical layer auditors and security teams often map to **secure SDLC**, **change management**, and **vulnerability management** themes common across regulated sectors.

### 12.1 Capabilities this repo’s CI/CD already contributes

| Capability | How this pipeline supports it | Typical audit / control mapping (illustrative) |
| ---------- | ------------------------------ | ---------------------------------------------- |
| **Change & release discipline** | Every merge to gated branches runs automated checks; Git history + Actions run IDs provide **who changed what, when, with what result**. **`workflow_dispatch`** supports controlled reruns. | SOC 2 **CC8** (change management); ISO 27001 **A.12.1** (operating procedures). |
| **Automated security testing (baseline)** | **Trivy** FS + SARIF; **TruffleHog** verified secrets; **CodeQL** (scheduled + on push/PR); scoped **Ruff** / **MyPy** on critical paths; **pytest** including tenant-isolation style tests. | SOC 2 **CC7**; HIPAA **§164.308(a)(1)(ii)(B)** as one *technical* input—not the whole safeguard. |
| **Dependency risk** | **Dependabot** (weekly PRs) + **Dependency review** on PRs (**high**+ severity gate). | Vulnerability / vendor management narratives when triage SLAs are defined in process. |
| **Functional / correctness regression** | Backend test suite + coverage floor; **OpenAPI drift** gate reduces accidental API breakage that could affect clients handling sensitive workflows. | Supports **integrity** and **availability** narratives when tied to risk assessment. |
| **Build reproducibility & provenance** | **Docker Buildx** on default branch after tests; **provenance + SBOM** attestations on push; **CycloneDX** SBOM artifacts with **retention**. | PCI DSS **6** (secure systems); customer due-diligence on supply chain. |
| **Frontend integrity** | **Lint + production build** catch whole classes of defects before release. | General product quality; supports change-control evidence. |

### 12.2 Regulated industries — how teams usually use CI/CD *alongside* other evidence

| Sector | CI/CD is strong evidence for… | Still required outside CI (examples) |
| ------ | ------------------------------ | -------------------------------------- |
| **Healthcare (e.g. HIPAA)** | Technical safeguards implemented in code (access patterns, tests), change control for software, vulnerability scanning artifacts. | BAA, workforce training, risk analysis, **production** audit logs & retention, breach process, physical/administrative safeguards. |
| **Finance (e.g. SOC 2, PCI if in scope)** | CC6/CC7/CC8-style narratives for logical access, monitoring, and change management when PR + CI + protected branches are documented. | Access reviews, vendor management, **production** logging/monitoring, incident response; PCI network segmentation and ASV scans if handling card data. |
| **Other regulated contexts (GDPR, GLBA, etc.)** | Demonstrating **secure development** and **documented release process** for processing systems. | Lawful basis, DPIA, data subject rights procedures, DPA, cross-border transfer mechanisms—**legal / process**, not pytest. |

### 12.3 Explicit non-claims

- This document does **not** state that running this workflow makes the product **HIPAA-compliant**, **SOC 2 certified**, **PCI DSS validated**, or equivalent.
- **Production** controls (encryption at rest in live DBs, KMS policies, backup/DR drills, SIEM retention, pen tests) are **orthogonal** to this YAML; reference your environment’s runbooks and GRC system for those.

### 12.4 Extending the pipeline further

Already in repo: **Dependabot**, **dependency review**, **CodeQL**, **Trivy**, **TruffleHog**, **image provenance/SBOM attestations**, **CycloneDX SBOM artifacts**.

Still typically **org- or process-level** (not only YAML): **branch protection + required reviewers**, **immutable artifact / log retention** aligned to policy, **IaC policy** (OPA/Conftest), **signed releases (Sigstore/cosign)** beyond GHCR defaults, **pentest** cadence, **DAST** against staging.

---

## 13. Maintainer checklist (PR readiness)

1. `cd backend && ./scripts/ruff_critical.sh && ./scripts/mypy_critical.sh && pytest -v --cov=app`
2. `cd frontend && npm ci && npm run lint && npm run build`
3. If HTTP routes changed: `python scripts/generate_openapi.py` and commit **`backend/docs/openapi-schema.json`**
4. If coverage drops below `fail_under` in `.coveragerc`: add tests or adjust omits/floor with team agreement
5. In GitHub: enable **branch protection** and set **required status checks** to match jobs you care about (e.g. `backend-test`, `integration-test`, `CodeQL`, `dependency-review` on PRs)

---

## 14. Known gaps (honest)

- **MyPy / Ruff** are **scoped**, not repo-wide.
- **Codecov** upload is **best-effort** in CI (token optional; step does not fail the job on upload errors).
- **Integration** smoke does not run the full pytest suite inside Compose; it only validates a running stack + a few endpoints.
- **`deploy`** is a stub; production delivery is out of band unless you replace that step.
- **CodeQL** and **`ci.yaml`** are separate; unless you mark CodeQL **required** in branch protection, a merge could theoretically proceed if only `ci.yaml` were green.

For product-level “shipped vs roadmap,” see the table in the root [README](../README.md).
