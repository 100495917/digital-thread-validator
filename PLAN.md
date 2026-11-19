# PLAN.md: MBSE DevOps/DevSecOps Pipeline with Digital Thread

> **Audience:** an autonomous coding agent. Follow phases in order. Each phase has tasks, files to create, and an **Acceptance** block that must pass before moving on. Commit after every phase with a conventional commit message.

## 0. Project goal

Build an environment that applies DevOps/DevSecOps to systems engineering. A change to a **requirement** or **model** must automatically trigger:

1. validation,
2. artifact generation,
3. tests,
4. security checks,
5. an update of the **digital thread** (traceability graph),
6. an **impact analysis** of the change.

Deliverables (from the course guideline):

- Working CI/CD pipeline
- Version control of engineering artifacts
- Automatic validation
- Test execution
- Report generation
- Change traceability
- Demonstration of the impact of a modification

## 1. Decisions (do not re-debate; change only if blocked)

| Topic | Choice |
|---|---|
| CI/CD | GitHub Actions |
| Language for tooling | Python 3.11+ |
| Requirements format | One YAML file per requirement in `requirements/` |
| Model format | YAML "system model" in `models/` (blocks, interfaces, behaviors) with a JSON Schema. PlantUML diagrams are *generated* from it |
| Digital thread store | NetworkX graph serialized to JSON (`digital_thread/thread.json`). Optional Neo4j export is a stretch goal |
| Test framework | pytest with a custom `req` marker |
| Docs / site | MkDocs (Material) published to GitHub Pages |
| Security | Gitleaks, Bandit, Semgrep, pip-audit, Trivy, Checkov (for IaC), SBOM via CycloneDX |
| Deploy | Docker + Docker Compose (staging), health-check smoke test |
| Example system | **Smart Thermostat Controller** (small, easy to trace) |

If a tool is unavailable offline, implement the check as a Python script and note it in `docs/decisions.md`.

## 2. Repository layout

```
.
├── PLAN.md
├── README.md
├── pyproject.toml
├── Makefile                      # make validate | trace | test | thread | impact | report | all
├── .pre-commit-config.yaml
├── .github/
│   ├── CODEOWNERS
│   ├── pull_request_template.md
│   └── workflows/
│       ├── ci.yml                # main pipeline
│       ├── pr-impact.yml         # impact comment on PRs
│       ├── release.yml           # baseline + changelog + deploy
│       └── pages.yml             # publish site
├── requirements/                 # REQ-001.yaml ...
├── models/
│   ├── system.yaml               # system model (source of truth)
│   └── schema/                   # JSON Schemas for requirements and model
├── src/thermostat/               # example system code
├── tests/
│   ├── unit/
│   ├── integration/
│   └── requirements/             # requirement-based tests
├── pipeline/                     # the tooling (python package `mbse`)
│   ├── mbse/
│   │   ├── cli.py                # entry point: `mbse <command>`
│   │   ├── loaders.py            # load requirements, model, code tags, tests
│   │   ├── validate_reqs.py
│   │   ├── validate_model.py
│   │   ├── trace.py              # traceability checks + RTM
│   │   ├── generate.py           # diagrams, docs, stubs
│   │   ├── thread.py             # digital thread build/update/query
│   │   ├── impact.py             # impact analysis
│   │   ├── select_tests.py       # selective testing
│   │   ├── reports.py            # aggregate reports
│   │   └── metrics.py            # DORA-style metrics
│   └── tests/                    # unit tests for the tooling itself
├── digital_thread/
│   ├── thread.json               # current graph
│   └── history/                  # one snapshot per run: <sha>.json
├── docs/                         # MkDocs sources (partly generated)
├── infra/
│   ├── Dockerfile
│   ├── docker-compose.staging.yml
│   └── main.tf (or ansible/)     # small IaC sample to scan
├── build/                        # generated output (gitignored)
│   ├── reports/
│   ├── diagrams/
│   └── site/
└── scripts/
    ├── demo.sh                   # scripted demo of the change-impact scenario
    └── bootstrap.sh
```

## 3. Data contracts

### 3.1 Requirement file (`requirements/REQ-XXX.yaml`)

```yaml
id: REQ-003
title: Heating activation threshold
text: The system shall activate heating when the measured temperature is below the setpoint minus 0.5 °C.
type: functional            # functional | performance | safety | security | interface
priority: high              # high | medium | low
owner: team-control
verification: test          # test | analysis | inspection | demonstration
status: approved            # draft | approved | deprecated
rationale: Prevents oscillation around the setpoint.
parent: REQ-001             # optional
```

### 3.2 Model (`models/system.yaml`)

```yaml
system: SmartThermostat
version: 1.0.0
elements:
  - id: BLK-controller
    kind: block              # block | interface | behavior | actor
    name: TemperatureController
    satisfies: [REQ-003, REQ-004]
    allocated_to: src/thermostat/controller.py
  - id: IF-sensor
    kind: interface
    name: SensorInterface
    satisfies: [REQ-002]
    allocated_to: src/thermostat/sensor.py
relations:
  - {from: BLK-controller, to: IF-sensor, type: uses}
```

### 3.3 Code and test tags

- Code: a comment `# @implements REQ-003` above the function or class.
- Tests: `@pytest.mark.req("REQ-003")`. A test may list several IDs.
- Register the `req` marker in `pyproject.toml`. A `conftest.py` plugin writes `build/reports/req_results.json` mapping `REQ-ID → [{test, outcome, duration}]`.

### 3.4 Digital thread graph

**Nodes** (all carry `id`, `type`, `path`, `sha256`, `version`, `last_changed_commit`):

`Requirement`, `ModelElement`, `CodeModule`, `Test`, `TestResult`, `Report`, `Commit`, `Release`

**Edges:**

| Edge | From → To |
|---|---|
| `DERIVES_FROM` | Requirement → Requirement (parent) |
| `SATISFIES` | ModelElement → Requirement |
| `ALLOCATED_TO` | ModelElement → CodeModule |
| `IMPLEMENTS` | CodeModule → Requirement |
| `VERIFIES` | Test → Requirement |
| `EXERCISES` | Test → CodeModule (from coverage data, best effort) |
| `RESULT_OF` | TestResult → Test |
| `CHANGED_IN` | any artifact → Commit |
| `INCLUDED_IN` | Commit → Release |

Run metadata attached to each snapshot: `commit_sha`, `author`, `timestamp`, `workflow_run_id`, `branch`, `tool_versions`.

## 4. Phases

### Phase 1: Bootstrap
**Tasks**
- Initialize `pyproject.toml` (package `mbse`, console script `mbse`, dev dependencies: pytest, pytest-cov, networkx, pyyaml, jsonschema, jinja2, click, mkdocs-material, bandit, pip-audit, cyclonedx-bom, pre-commit, yamllint, markdownlint-cli via npm or pymarkdown).
- Create `Makefile`, `.gitignore`, `.editorconfig`, `.pre-commit-config.yaml` (yamllint, ruff, gitleaks, `mbse validate` on staged requirement/model files).
- Create `CODEOWNERS` (requirements → `@req-owners`, models → `@architects`, `src` → `@devs`) and PR template with checklist (requirement IDs, impact reviewed).
- Add `docs/decisions.md` recording the decisions in §1.

**Acceptance:** `pip install -e .[dev]` works; `mbse --help` lists the commands; `pre-commit run --all-files` passes on the empty skeleton.

### Phase 2: Example project (Smart Thermostat)
Generate a small but realistic system so every pipeline stage has something to do.

**Requirements (create at least 12):**

| ID | Type | Statement (shall) |
|---|---|---|
| REQ-001 | functional | Maintain room temperature within ±1 °C of the setpoint. |
| REQ-002 | interface | Read temperature from the sensor every 5 seconds. |
| REQ-003 | functional | Activate heating when temperature < setpoint − 0.5 °C. |
| REQ-004 | functional | Deactivate heating when temperature ≥ setpoint + 0.5 °C. |
| REQ-005 | safety | Force heating off if temperature exceeds 30 °C. |
| REQ-006 | safety | Enter fail-safe (heating off) if the sensor reading is missing for 3 consecutive cycles. |
| REQ-007 | performance | Respond to a setpoint change within 2 seconds. |
| REQ-008 | functional | Accept setpoints only between 5 °C and 30 °C. |
| REQ-009 | interface | Expose current state through a REST endpoint `GET /status`. |
| REQ-010 | interface | Accept setpoint updates through `PUT /setpoint`. |
| REQ-011 | security | Require an API token for `PUT /setpoint`. |
| REQ-012 | security | Not log API tokens. |
| REQ-013 | performance | `GET /status` shall respond in under 100 ms (p95) under 50 req/s. |

**Model (`models/system.yaml`):** blocks `TemperatureController`, `SensorInterface`, `HeaterActuator`, `SafetyMonitor`, `SetpointValidator`, `RestApi`, `AuthMiddleware`; interfaces between them; each block satisfies one or more requirements and is allocated to a source module.

**Code (`src/thermostat/`):** `controller.py` (hysteresis logic), `sensor.py` (simulated sensor), `heater.py`, `safety.py`, `validator.py`, `api.py` (FastAPI or Flask), `auth.py`. Add `# @implements` tags. Keep total code under ~400 lines.

**Tests:**
- `tests/unit/`: pure logic.
- `tests/integration/`: API tests with the test client.
- `tests/requirements/`: at least one test per requirement, tagged with `req`. Leave **REQ-013** verified by a simple load test script (locust or a Python timing loop) so performance appears in the thread.

**Acceptance:** `pytest` passes; every requirement has ≥1 `@implements` and ≥1 `req`-tagged test; line coverage ≥ 85%.

### Phase 3: Validation tooling
**3.1 JSON Schemas** in `models/schema/` for requirements and the model. `mbse validate schema` validates all files and prints file + path + message on error.

**3.2 Requirements quality (`validate_reqs.py`)** with these rules, each with an ID, severity, and message:

| Rule | Check |
|---|---|
| RQ-001 | ID unique and matches `REQ-\d{3}` |
| RQ-002 | Text contains "shall" (exactly one normative statement) |
| RQ-003 | No ambiguous terms: `fast, quickly, user-friendly, easy, flexible, appropriate, as needed, etc., and/or, approximately, TBD` |
| RQ-004 | Measurable terms in performance requirements (a number and a unit) |
| RQ-005 | Mandatory fields present (owner, priority, verification) |
| RQ-006 | `parent` references an existing requirement; no cycles |
| RQ-007 | Text length ≤ 300 chars |
| RQ-008 | Approved requirements cannot have verification `TBD` |

Output a **quality score** (% of rules passed per requirement and overall) to `build/reports/req_quality.json`.

**3.3 Model validation (`validate_model.py`):**
- Unique element IDs, naming convention (blocks `PascalCase`, IDs `BLK-`/`IF-`/`BHV-` prefixes).
- All `satisfies` targets exist; all `allocated_to` paths exist.
- No orphan blocks (every block has ≥1 relation or ≥1 satisfied requirement).
- No dangling relations; interface elements connected to ≥2 blocks.

**3.4 Linting:** yamllint, markdownlint, ruff, plus `mbse validate all` as the aggregate command. Exit non-zero on any `error`; warnings are reported but do not fail.

**Acceptance:** unit tests in `pipeline/tests/` cover each rule with a passing and failing fixture. `mbse validate all` passes on the example project and fails on seeded bad fixtures.

### Phase 4: Traceability and RTM
**Tasks (`trace.py`):**
- Build the link tables from requirements, model, code tags, and test markers.
- Checks (errors unless noted):
  - Every approved requirement is satisfied by ≥1 model element.
  - Every approved requirement is implemented by ≥1 code module (warning if verification is `inspection`/`analysis`).
  - Every approved requirement with verification `test` has ≥1 test.
  - No link points to a non-existent requirement or element.
  - Deprecated requirements have no active tests (warning).
- Generate the **RTM** in three formats: `build/reports/rtm.csv`, `rtm.md`, and `rtm.html`. Columns: Req ID, Title, Priority, Model elements, Code, Tests, Last result, Status.
- Compute metrics: **traceability coverage** (% of requirements with full chain) and **requirements verification coverage** (% of requirements whose tests passed).

**Acceptance:** RTM generated for the example project with 100% chain coverage. Removing a test tag makes `mbse trace check` fail and name the requirement.

### Phase 5: Artifact generation (`generate.py`)
- **Diagrams:** PlantUML (or Mermaid) block definition diagram and requirement diagram generated from `system.yaml` and requirements. Save sources in `build/diagrams/*.puml`. Render to SVG if PlantUML or Graphviz is available; otherwise embed Mermaid in the docs.
- **Docs:** generate `docs/generated/requirements.md`, `docs/generated/architecture.md`, `docs/generated/rtm.md` with Jinja2 templates. Hand-written docs live in `docs/` and `mkdocs.yml` includes both.
- **Interface skeleton:** generate an OpenAPI file `build/openapi.json` from the API (and check it against REQ-009 and REQ-010 endpoints).
- **Test stubs:** `mbse generate test-stubs` lists requirements without tests and writes pytest skeletons to `build/stubs/` (not committed).
- **SBOM:** `cyclonedx-py` to `build/reports/sbom.json`.

**Acceptance:** `mkdocs build --strict` succeeds; generated files are deterministic (running twice produces identical output).

### Phase 6: Tests and coverage
- Configure pytest: JUnit XML (`build/reports/junit.xml`), coverage XML and HTML, `req` marker plugin producing `req_results.json`.
- Mutation or negative testing is optional.
- Performance check for REQ-013 as a separate marked test (`@pytest.mark.perf`) that runs in the staging job.
- `mbse reqcov` combines `req_results.json` and requirements to produce requirements coverage; fail the gate below a configurable threshold (default 90%).

**Acceptance:** all reports exist after `make test`; a deliberately failing test appears in the report mapped to its requirement.

### Phase 7: Security (DevSecOps)
| Check | Tool | Gate |
|---|---|---|
| Secrets in repo and history | Gitleaks | any finding fails |
| Python SAST | Bandit + Semgrep (`p/python`) | HIGH fails |
| Dependency vulnerabilities | pip-audit | HIGH/CRITICAL fails |
| Container image | Trivy | CRITICAL fails |
| IaC | Checkov on `infra/` | HIGH fails |
| Security requirements | Custom: every `type: security` requirement must trace to a test | fails if missing |

- Output SARIF where supported and upload with `github/codeql-action/upload-sarif`.
- Add a security summary to `build/reports/security.json` (counts by severity and tool).
- Optional: sign the image with Cosign (keyless) in the release workflow; require signed commits on `main` (document branch protection settings in `docs/devsecops.md`).

**Acceptance:** all scanners run in CI; a seeded fake secret on a test branch fails the pipeline; a security requirement without a test fails `mbse trace check`.

### Phase 8: Digital thread (`thread.py`)
**Tasks**
- `mbse thread build`: load all artifacts, compute `sha256` of each file, create nodes and edges per §3.4, add test results from `req_results.json` and JUnit, add commit and run metadata (from `git` and GitHub env vars like `GITHUB_SHA`, `GITHUB_RUN_ID`; fall back to local git).
- `mbse thread update`: load previous `thread.json`, diff against the new build, and record `added`, `removed`, `modified` nodes and edges. Store the snapshot in `digital_thread/history/<sha>.json` and write `build/reports/thread_diff.md`.
- `mbse thread query`: CLI queries, e.g. `--upstream REQ-003`, `--downstream REQ-003`, `--why-failed TEST-id`, `--history REQ-003` (all commits touching it).
- **Staleness:** mark a downstream node `stale` when an upstream node's hash changed after the downstream node's last verification (e.g. requirement edited but tests not updated).
- Visualization: export to GraphML/DOT and render `build/reports/thread.svg`; also create an interactive `docs/thread.html` (pyvis or D3 from the JSON) that is included in the site.
- Persistence in CI: commit `thread.json` and history to a dedicated `digital-thread` branch (or upload as artifact and push to Pages) so history survives between runs.
- Stretch: `mbse thread export-neo4j` generating Cypher.

**Acceptance:** after a run, `thread.json` contains all node and edge types for the example; `mbse thread query --downstream REQ-003` lists the model element, code, tests, and latest results; editing a requirement makes its downstream tests show as `stale` until re-run.

### Phase 9: Impact analysis and selective testing
**Tasks**
- `mbse impact --base <ref> --head <ref>`:
  1. `git diff --name-only` to find changed files, map them to graph nodes (requirement, model, code, test).
  2. Traverse the graph: from requirements, go downstream to model, code, tests, and docs; from code, go upstream to requirements and downstream to tests; from tests, go upstream to requirements.
  3. Classify each affected artifact: `directly_changed`, `impacted`, `needs_review`, `needs_retest`.
  4. Output `build/reports/impact.json` and `impact.md` (tables by artifact type, plus a risk level: number of safety/security requirements touched, depth of propagation).
- `select_tests.py`: produce pytest node IDs for `needs_retest` tests; `make test-selective` runs only those. The full suite still runs on `main`; selective runs on PRs *in addition* to the full suite (report time saved).
- `pr-impact.yml`: on `pull_request`, run impact analysis and post or update a single PR comment with the markdown (use `marocchino/sticky-pull-request-comment` or `gh api`).
- Before/after: include an RTM diff (`rtm_diff.md`) and thread diff in the comment.

**Acceptance:** changing REQ-003 yields an impact report listing `BLK-controller`, `controller.py`, the tests tagged REQ-003, and any child requirements; PR comment appears; selective run executes exactly those tests.

### Phase 10: Reporting and site
- `mbse report`: produce `build/reports/summary.md` and `summary.json` aggregating validation score, trace coverage, test results, coverage, security counts, impact, and thread diff. Pipeline status badge at the top.
- HTML test report (pytest-html or Allure).
- `pages.yml`: build MkDocs, copy `build/reports/` and `thread.html` into the site, and deploy to GitHub Pages. Site sections: Overview, Requirements, Architecture, RTM, Test results, Security, Digital thread, Impact of last change, Metrics.
- Upload all reports as workflow artifacts (retention 30 days).

**Acceptance:** the site is built locally with `make site` and in CI; every section renders without broken links (`mkdocs build --strict`).

### Phase 11: Versioning, baselines, releaseth a required reviewer for manual approval before a `production` placeholder job.
- Rollback: tag images with commit SHA; a `rollback.yml` workflow redeploys the previous tag.

**Acceptance:** after merge to `main`, staging comes up and smoke tests pass; the deploy is recorded in the digital thread (`Release`/`Deployment` node).

### Phase 13: Metrics and feedback
- `mbse metrics` computes from the GitHub API or git history: lead time for changes (commit → deploy), deployment frequency, change failure rate (failed pipelines / total), and mean time to restore. Write `build/reports/metrics.json` and a page on the site.
- Pipeline-level metrics: duration per stage, flaky test count.
- Feedback loop: a script that reads staging runtime metrics (e.g. observed p95 latency) and opens or updates a GitHub Issue if a requirement's threshold is violated, linking the requirement ID.

**Acceptance:** metrics page shows non-empty values after at least 3 runs.

### Phase 14: Pipeline definition (`ci.yml`)
Stages and dependencies:

```
trigger (push/PR on requirements/**, models/**, src/**, tests/**, infra/**)
  └─ lint-validate ─┬─ trace-check ─┬─ generate ─┬─ test ──┬─ security (parallel matrix) ─┬─ thread-update ─ impact ─ report ─ pages
                    │               │            │         │                               │
                    └───────────────┴────────────┴─────────┴──────────────────────────────┴─ deploy-staging (main only)
```

Rules:
- Use path filters, but always run a minimal job on any change so required checks never stay pending.
- Cache pip and pre-commit.
- Fail-fast on validation; run security jobs in parallel; `thread-update` and `report` run with `if: always()` so failures are still recorded in the thread.
- Required status checks on `main`: `lint-validate`, `trace-check`, `test`, `security`.
- All jobs upload their outputs to `build/reports/`; the `report` job downloads and aggregates them.

**Acceptance:** a push touching only a requirement file runs the full chain; a PR shows green checks and the impact comment.

### Phase 15: Demo
Create `scripts/demo.sh` and `docs/demo.md` describing a repeatable scenario, with expected outputs for each step.

1. **Baseline state:** pipeline green, thread and RTM generated.
2. **Change a requirement:** modify REQ-003 threshold from 0.5 °C to 0.3 °C on a branch and open a PR.
3. **Observe:** pipeline triggers automatically; validation passes; impact comment lists the affected model block, code, tests, and child requirement; only the affected tests are re-run first.
4. **Deliberate failure:** the controller still uses 0.5 °C, so `test_req_003` fails; the report maps the failure to REQ-003; thread marks nodes as `stale/failed`.
5. **Fix:** update the code and model; pipeline goes green; thread diff and RTM diff show the change; the staleness flags clear.
6. **Release:** merge, tag `v1.1.0`, show changelog, new baseline, and `mbse baseline diff v1.0.0 v1.1.0`.

**Additional negative demos** (each on a throwaway branch, scripted):
- Add an ambiguous requirement ("The system shall respond quickly") → validation fails (RQ-003, RQ-004).
- Add a requirement with no model link or test → trace check fails.
- Commit a fake API token → Gitleaks fails.
- Add a dependency with a known CVE → pip-audit fails.

**Acceptance:** `scripts/demo.sh` runs end to end locally (against a local git repo, without GitHub) and prints a summary of impacted artifacts. The same scenario is reproducible in GitHub with recorded PR links in `docs/demo.md`.

## 5. Global acceptance checklist

- [ ] All requirements, models, and code are version-controlled; baselines tagged
- [ ] Any change to `requirements/` or `models/` triggers the pipeline automatically
- [ ] Requirements and model validation run and gate the pipeline
- [ ] RTM and docs are generated automatically and deterministically
- [ ] Unit, integration, and requirement-based tests run; requirements coverage is reported
- [ ] Security scans (secrets, SAST, SCA, container, IaC) run with gates
- [ ] Digital thread JSON is updated every run with history and diff
- [ ] Impact analysis is generated, posted on PRs, and drives selective testing
- [ ] Reports published on a project site
- [ ] Staging deployment with smoke tests and rollback
- [ ] Metrics page available
- [ ] Demo script reproduces the change-impact scenario, including a deliberate failure
- [ ] README explains setup, commands, architecture, and how to run the demo

## 6. Working rules for the agent

1. Work phase by phase. Do not start a phase until the previous acceptance block passes.
2. Write unit tests for every function in `pipeline/mbse/`; keep the tooling at ≥ 80% coverage.
3. Keep tooling deterministic: sorted keys, stable ordering, no timestamps in generated files (timestamps only in run metadata).
4. Every CLI command returns a non-zero exit code on failure and writes machine-readable output (JSON) plus a human-readable summary.
5. Prefer small, readable code over frameworks. No external services are required to run locally; GitHub-specific steps must degrade gracefully when env vars are missing.
6. Document every command in `README.md` and every pipeline stage in `docs/pipeline.md` (with a diagram).
7. If a tool cannot be installed in the environment, implement a minimal Python fallback, record it in `docs/decisions.md`, and continue.
8. At the end, run `make all` and `scripts/demo.sh`, paste their output into `docs/demo.md`, and fix anything that fails.

## 7. Suggested order of effort (if time is limited)

Must have: Phases 1, 2, 3, 4, 6, 8, 9, 10, 14, 15.
Should have: Phases 5, 7, 11.
Nice to have: Phases 12, 13, Neo4j export, Cosign signing.

- Conventional commits enforced via `commitlint` (or a Python check), and requirement IDs required in commit scope for changes under `requirements/`, `models/`, `src/` (warning only, error with a label `strict-trace`).
- `release.yml` on tag `v*` or manual dispatch:
  1. Run the full pipeline.
  2. Freeze a **baseline**: `baselines/baseline-<version>.json` with the hash of every requirement, model, and code file, plus the RTM and thread snapshot.
  3. Generate the changelog with `git-cliff` (group by type, list affected requirement IDs).
  4. Create the GitHub Release with SBOM, RTM, and reports attached.
- `mbse baseline diff v1.0.0 v1.1.0` to show requirement, model, and test changes between baselines.
- Git LFS config for large binaries (`*.png`, `*.pdf`, `*.step`, `*.slx`) in `.gitattributes`.

**Acceptance:** tagging `v1.0.0` creates a release with baseline, changelog, SBOM, and RTM.

### Phase 12: Delivery to staging
- `infra/Dockerfile` (multi-stage, non-root user, healthcheck).
- `infra/docker-compose.staging.yml` bringing up the API and a monitoring stack (Prometheus + Grafana optional).
- CI job `deploy-staging` (on `main` only, after all gates): build image, scan, push to GHCR, deploy with Compose on the runner, run smoke tests (`/status`, auth failure, setpoint range) plus the REQ-013 performance test.
- Use a GitHub Environment `staging` wi
