```markdown
# GitHub Actions CI/CD Guide — Python projects (with Web-Scale Optimization)

This document describes a recommended GitHub Actions CI/CD setup for Python services and libraries, plus advanced optimization techniques for web-scale systems (frontend, business layer, backend) and best practices for Test‑Driven Development (TDD), refactoring, and agile software craftsmanship.

Goals
- Prevent regressions with formatters, linters, type checks, and tests on PRs.
- Ensure reproducible builds and cached dependencies for speed.
- Automate releases and controlled deployments with environment protection.
- Surface security and dependency issues early.
- Measure and enforce performance budgets and optimizations as part of CI/CD.
- Encourage craftsmanship: TDD, continuous refactoring, pair review, and learning culture.

Key principles
- Fail fast for style/type issues; run expensive checks after fast gate checks pass.
- Measure before optimizing — use profiling and metrics to identify real hotspots.
- Prefer simple, maintainable solutions; optimize where it matters using data.
- Make performance and scalability part of PR review and CI (profiling, perf tests).
- Practice TDD where practical; integrate refactoring and tech‑debt pay‑down into regular cadences.
- Keep feedback loops short (fast tests, pre-commit hooks, small PRs).

Required repo settings
- Branch protection rules for main: require CI checks (lint/type/tests/perf where applicable), require PR reviews, require up-to-date branch before merge.
- Repository Secrets for publish tokens, cloud credentials, and environment-specific secrets.
- Environments with required reviewers for staging/production.
- Performance baselines and test-data artifacts stored or reproducible.
- CODEOWNERS, PR/ISSUE templates, CONTRIBUTING.md and SECURITY.md.

Recommended CI checks
- Formatting: black, isort
- Linting: ruff/flake8
- Type checking: mypy/pyright
- Unit tests: pytest with coverage; fast unit tests for PR feedback
- Integration/smoke tests for critical flows
- Dependency/supply-chain scans: Dependabot + CodeQL/Snyk
- Performance/regression tests and profiling jobs
- Mutation testing (scheduled or on major PRs) to improve test quality

TDD, Refactoring & Agile Software Craftsmanship

1) Test-Driven Development (TDD)
- Philosophy: Red → Green → Refactor. Write a failing test that describes desired behavior, implement minimal code to pass, then refactor.
- Practical TDD rules:
  - Prefer unit tests for fast-feedback behavior validation. Keep unit tests <100ms where possible.
  - Write tests that assert behavior, not implementation details. Use public APIs for tests.
  - Keep tests deterministic and independent; avoid shared global state.
  - Maintain a clear test pyramid: many fast unit tests, fewer integration tests, even fewer E2E tests.
- CI enforcement:
  - Require tests to run and pass on PRs.
  - Require coverage for new code (e.g., ensure new modules have tests).
  - Integrate mutation testing (mutmut or similar) in scheduled workflows or on major releases to increase confidence.
- Tooling & practices:
  - Use pytest with parametrization, fixtures, and markers (unit/integration/smoke).
  - Use test doubles (mocks/fakes) at unit level; use contract tests for real integrations.
  - Pair or mob on test-writing for complex flows to spread knowledge.

2) Refactoring
- Continuous refactoring is part of daily work, not a separate phase.
- Small, safe refactors:
  - Keep PRs small and focused: one refactor per PR where possible.
  - Use automated formatting (black/isort) and lint auto-fixes (ruff) to remove noise.
  - Add unit tests before refactoring if behavior is not already covered.
- Detection & automation:
  - Use static analysis (mypy, ruff), complexity checks (radon), duplication detection, and code-quality tools (SonarCloud/CodeClimate) in CI.
  - Add a scheduled "code health" job that reports complexity, duplicated code, and trendlines.
- Policies & governance:
  - Boy Scout Rule: leave the codebase cleaner than you found it.
  - Track tech debt as first-class backlog items; schedule periodic pay-down and review.
  - Use CODEOWNERS and small module ownership to manage large refactors.
- Safe rollout:
  - Run full test suite and perf baselines after refactors touching hot paths.
  - Use feature flags when refactors cross public API boundaries.

3) Agile Software Craftsmanship
- Team practices:
  - Definition of Done (DoD): code compiles, tests pass, type checks, lint passed, docs/README updated, and performance considerations noted for critical paths.
  - Pair programming & mobbing on high-risk or knowledge-transfer tasks.
  - Regular code reviews focused on correctness, readability, and design — not just formatting.
  - Encourage coding katas and lunch-and-learns to build shared skillsets (TDD workshops, design-pattern sessions).
- Process & delivery:
  - Trunk-based development or short-lived feature branches with frequent merges.
  - Use feature flags and canary releases for incremental rollouts.
  - Keep user stories small and implementable within a sprint; include acceptance tests as part of the ticket.
  - Maintain a blameless postmortem culture and continuous improvement via retrospectives.
- Documentation & mentoring:
  - Maintain onboarding docs, architectural overviews, and runbooks.
  - Rotate on-call and review duties to spread operational knowledge.

CI/CD Integration for TDD & Refactoring

1) Pre-commit & local parity
- Ensure developers run the same linters/formatters locally:
  - .pre-commit-config.yaml runs black, isort, ruff, detect-secrets, mypy, and basic tests.
- Enforce pre-commit on CI (CI should re-run linters and fail fast if pre-commit would have rejected).

2) PR checks & gating
- Required jobs for PRs:
  - Formatting check (black --check, isort --check-only)
  - Linting (ruff/flake8)
  - Type checks (mypy/pyright)
  - Unit tests (fast subset)
  - Full tests & coverage (dependent job)
- Labels / templates:
  - PR template should include checkboxes for TDD/refactor practices:
    - Tests added? (Y/N)
    - Behavior covered by tests? (unit/integration)
    - Complexity considerations documented?
    - Rollout/flagging plan for risky changes?

3) Mutation testing (improve test quality)
- Run mutation testing in scheduled workflow or nightly for main branch (tools: mutmut, cosmic-ray).
- Use results to identify weak tests and add coverage where necessary.
- Do not block trivial PRs with mutation testing, but triage high-impact mutation escapes.

4) Performance & refactor safety
- For refactors touching hot paths, require:
  - Microbenchmarks or profiling evidence that change is safe.
  - Perf tests in CI/staging with baseline comparison (scheduled or on-demand).
- Upload profiler flamegraphs to PR for reviewer inspection when relevant.

Example PR checklist (add to .github/PULL_REQUEST_TEMPLATE.md)
- [ ] Small, focused change (one logical purpose)
- [ ] Tests: unit/integration added/updated
- [ ] TDD followed where feasible (link to failing test if used)
- [ ] CI: linters, type checks, tests passed
- [ ] Performance impact noted (N/A if not applicable)
- [ ] Documentation and changelog updated
- [ ] Code owner review requested

Sample GitHub Actions additions

A) Fast "TDD gate" job for PRs (conceptual snippet)
```yaml
name: TDD-Gate
on: [pull_request]
jobs:
  tdd-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      - name: Install deps
        run: |
          pip install -r requirements-dev.txt
      - name: Run format/lint/type
        run: |
          black --check .
          isort --check-only .
          ruff .
          mypy src
      - name: Run unit tests (fast)
        run: |
          pytest tests/unit -q --maxfail=1 -k "not integration"
```

B) Scheduled mutation testing job (nightly/main)
```yaml
name: Mutation-Test
on:
  schedule:
    - cron: '0 3 * * *' # nightly
jobs:
  mutation:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      - name: Install deps and mutmut
        run: |
          pip install -r requirements-dev.txt
          pip install mutmut
      - name: Run mutation tests (mutmut)
        run: |
          mutmut run --paths-to-mutate src
      - name: Upload mutmut report
        uses: actions/upload-artifact@v4
        with:
          name: mutmut-report
          path: .mutmut-cache
```

Best practices summary (practical rules)
- TDD: write failing test first where reasonable; keep tests fast & deterministic.
- Refactor: one refactor per PR, small commits, add tests before modifying behavior; run complexity/duplication checks.
- Agile craftsmanship: DoD, pair programming, trunk-based development, feature flags, keep PRs small, mentor juniors.
- CI: enforce tests, type checks, linters; schedule heavier quality jobs (mutation, perf, code-health) nightly.
- Observability: require telemetry for new code paths; add dashboards and alerting for critical SLIs.

Where to put these items in your repo
- CI workflows: .github/workflows/ (add tdd-gate.yml, mutation.yml, perf.yml)
- PR template: .github/PULL_REQUEST_TEMPLATE.md (add TDD/refactor checklist)
- Contributing & style: CONTRIBUTING.md, CODE_OF_CONDUCT.md
- Runbooks & SLOs: docs/SLO.md, docs/runbooks/

## Enterprise-Scale Engineering Practices (MAANG/MULAN Inspired)

### API Design and Service Reliability
- **API Stability and Versioning**
  - Adopt formal API versioning (e.g., /v1/, /v2/) with explicit deprecation policies.
  - Ensure backward compatibility and define a deprecation window for breaking changes.

- **Contract-First Design**
  - Use OpenAPI, GraphQL schemas, or Protobuf for API definitions.
  - Enforce schema validation in CI/CD pipelines.

- **Observability per Endpoint**
  - Track latency, error rates, saturation (golden signals) per API.
  - Integrate automatic dashboards for endpoint performance.

- **Graceful Degradation & Fallbacks**
  - Define fallback strategies for critical endpoints (e.g., default response, stale cache).
  - Test fallback paths and verify resilience during outages.

- **API Security Practices**
  - Integrate static/dynamic security scanning (e.g., OWASP ZAP, DAST tools).
  - Enforce OAuth2, rate limiting, and authentication schema compliance.

---

### Service Uptime, SLOs, and Incident Management
- **Service Level Objectives and Error Budgets**
  - Define SLIs/SLOs for every service; track compliance weekly.
  - Introduce error budgets as velocity control mechanisms.

- **Severity-Based Incident Taxonomy**
  - Establish SEV0–SEV3 classification with clear ownership and escalation.
  - Automate alerting thresholds tied to SEV levels.

- **Postmortems and Blameless RCA**
  - Standardize a blameless postmortem template (5 Whys, action items).
  - Include detection time, MTTR, user impact, and missed alert opportunities.

- **Runbooks and Escalation Paths**
  - Maintain updated runbooks for all alertable services.
  - Include escalation ladders, rollback steps, and diagnostics per alert.

- **Failure Injection and Chaos Testing**
  - Conduct regular chaos drills (e.g., shutdowns, latency injections).
  - Validate team readiness and system resilience.

---

### DevOps and SRE Practices for Cloud-Native Systems
- **Golden Signals Monitoring**
  - Mandate collection of latency, traffic, errors, and saturation.
  - Define alert thresholds and auto-tuning policies.

- **Auto-Remediation and Self-Healing**
  - Enable safe automated responses for common failure scenarios.
  - Track remediation success rates and error recurrence.

- **Release Guardrails and Progressive Delivery**
  - Implement canary deployments with automated rollback on anomalies.
  - Shadow traffic and anomaly detection in staging.

- **Infrastructure as Code (IaC)**
  - Use Terraform/Pulumi for infrastructure with CI/CD verification.
  - Enforce peer review and linting for infrastructure changes.

- **Service Ownership Model**
  - Document ownership, SLOs, runbooks, and alert routing for each microservice.

---

### Code Review Enhancements
- **Reviewer Load Management**
  - Automate reviewer assignment based on expertise and load.
  - Avoid overburdening gatekeepers by enforcing reviewer rotation.

- **Code Health as a Review Goal**
  - Define and enforce readability, testability, and maintainability goals.
  - Tag PRs with complexity/criticality for focused review depth.

- **Review SLA and Metrics**
  - Define review SLA (e.g., 24-hour first response).
  - Track metrics: time to review, #comments, coverage quality.

---

### Developer Onboarding and Ramp-Up
- **Starter Projects**
  - Assign scoped onboarding tasks to exercise CI/CD and ownership.

- **Buddy Assignment**
  - Pair each hire with a mentor/buddy for first 30 days.

- **Onboarding Checklist**
  - Define 30/60/90-day expectations: tech stack, deploys, ownership.
  
- **Ramp Metrics**
  - Track: time to first commit, first review, first deploy, satisfaction survey.

---

### Tooling, Automation, and Developer Productivity
- **API Schema Validation in CI**
  - Validate OpenAPI/GraphQL/Protobuf against implementation pre-merge.

- **Pre-Release Regression Dashboards**
  - Visual diffs of latency, throughput, error rates for each release.

- **ChatOps Integration**
  - Slack/GitHub bots for triggering deployments, surfacing PR test results, or linking runbooks.

- **Developer Experience Dashboards**
  - Track PR cycle time, review depth, CI flake rates, deployment frequency (DORA).

---

### Engineering Culture and Craftsmanship
- **Error Budget Reviews**
  - Monthly reviews of SLO compliance and release reliability.

- **Tech Debt Transparency**
  - Maintain visible tech debt register tied to component owners.

- **Mob Programming Policies**
  - Require mobbing for complex, high-risk, or infra-wide changes.

- **Coding Katas and Technical Brown Bags**
  - Biweekly TDD or architecture-focused sessions to reinforce shared standards.

---

### Optional Advanced Modules (Edge Case Enhancements)

#### Security and Compliance
- **Threat Modeling Integration**
  - Require STRIDE or equivalent threat modeling during design reviews.
- **SBOM Generation and Compliance**
  - Produce Software Bill of Materials (SBOM) as part of release artifacts.
- **Security Champion Rotation**
  - Rotate a security liaison role per team to audit and train regularly.

#### Data Engineering and ML Pipelines
- **Experiment Tracking**
  - Standardize ML experimentation using tools like MLflow or Weights & Biases.
- **Data Versioning**
  - Use DVC or LakeFS for immutable data sets in model training.
- **Model Monitoring**
  - Define latency, accuracy drift, and prediction distribution as SLIs.

#### Remote and Distributed Collaboration
- **Asynchronous Review Protocols**
  - Document rules for async PR reviews, architecture discussions, and incident handoffs.
- **Time Zone-Aware Rotations**
  - Assign primary and secondary responders across time zones for global systems.

#### Accessibility and Inclusive Engineering
- **UI Accessibility Checks**
  - Include a11y testing in CI using Axe or Lighthouse for frontend systems.
- **Inclusive Language Linting**
  - Use linters (e.g., alex) to catch non-inclusive language in code and docs.

#### Change Management and Governance
- **RFC Process for Major Changes**
  - Define a lightweight Request For Comments template and workflow.
- **Feature Lifecycle Definition**
  - Document lifecycle stages (Alpha, Beta, GA, Deprecated) and expectations.
- **Change Advisory Board (CAB)**
  - For regulated domains, define a lightweight CAB workflow for review and audit.
```