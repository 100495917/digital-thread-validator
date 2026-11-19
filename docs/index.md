# Digital Thread Validator

This project applies DevOps and DevSecOps practices to Model-Based Systems
Engineering. Requirements, the system model, code, and tests are versioned as
plain text, and a pipeline validates them, checks traceability, generates
artifacts, and runs requirement-based tests.

The working example is a **Smart Thermostat Controller**: YAML requirements in
`requirements/`, a block/interface model in `models/system.yaml`, Python code
tagged with requirement identifiers in `src/thermostat/`, and pytest tests
tagged with `@pytest.mark.req(...)` markers. The pipeline derives links between
these artifacts and writes reports under `build/`.

## Sections

- [Requirements](generated/requirements.md) — approved requirements and their
  attributes, generated from `requirements/*.yaml`.
- [Architecture](generated/architecture.md) — blocks, interfaces, and behaviors
  generated from the system model.
- [RTM](generated/rtm.md) — requirement traceability matrix linking
  requirements to model elements, code, and tests.
- [Test results](generated/tests.md) — test counts, failures, and requirement
  coverage from the latest JUnit and coverage reports.
- [Security](generated/security.md) — security gate status and scanner findings.
- [Impact of last change](generated/impact.md) — artifacts changed or affected by
  the last Git diff, with risk level and the tests to re-run.
- [Metrics](generated/metrics.md) — current pipeline counts for requirements,
  tests, coverage, and traceability.
- [Summary](generated/summary.md) — one-page pipeline status with links to every
  report.
- [Decisions](decisions.md) — binding architecture and tooling decisions.
- [Pipeline](pipeline.md) — pipeline stages, impact analysis, reporting,
  commands, and report locations.
- [Digital thread](thread.md) — the versioned graph of requirements, model
  elements, code, tests, results, reports, commits, and releases, including
  snapshots, diffs, staleness, and interactive visualization.
- [Demo](demo.md) — an end-to-end walkthrough of the change-impact loop,
  negative demos, and GitHub reproduction steps.

## Delivery and releases

Releases, baselines, deployment, and DORA metrics are documented in
[Pipeline](pipeline.md):

- **Baselines** — `mbse baseline freeze VERSION` writes
  `baselines/baseline-<VERSION>.json` with artifact hashes, RTM rows, and the
  thread snapshot; `mbse baseline diff OLD NEW` writes
  `build/reports/baseline_diff.json` and `.md`.
- **Releases** — a `v*` tag runs the full release workflow (validation,
  traceability, tests, security, thread update), freezes the baseline, writes
  the changelog, and attaches the baseline, changelog, RTM, SBOM, summary, and
  thread snapshot to a GitHub Release.
- **Commits** — `mbse commits check --range RANGE [--strict]` enforces
  conventional commit subjects and `REQ-nnn` references on traced artifacts.
- **Staging** — the deploy workflow builds and scans a Docker image, starts
  `infra/docker-compose.staging.yml`, runs smoke tests including the REQ-013 p95
  latency check, and records a `Deployment` node in the digital thread;
  `Rollback` redeploys a previous image tag.
- **Metrics** — `mbse metrics` writes `build/reports/metrics.json` with DORA
  deployment frequency, lead time, change failure rate, MTTR, and pipeline
  test/coverage counts; `scripts/feedback.py` turns a REQ-013 latency violation
  into a GitHub issue.
- **CI** — `ci.yml` gates pulls and main pushes on lint/validation, trace,
  generation, tests with requirement coverage, security, impact, and the
  aggregate report, then deploys staging on `main`.

## Quick start

```bash
make validate        # validate requirement YAML, the model, and their schemas
make test            # run pytest and write JUnit, coverage, and req-result reports
make trace           # check requirement-to-model-to-code-to-test traceability
make impact          # analyse the diff against origin/main and write impact reports
make test-selective  # run only the tests selected by the latest impact report
make report          # write summary.json/summary.md and the generated site pages
make site            # generate reports and build the MkDocs site with --strict
```

Release, delivery, and metrics commands:

```bash
mbse baseline freeze v1.0.0                     # freeze a baseline
mbse baseline diff v1.0.0 v1.1.0                # compare two baselines
mbse changelog --version v1.1.0 \
  --output build/reports/changelog.md           # conventional-commit changelog
mbse commits check --range origin/main..HEAD    # conventional commit checks
mbse metrics                                    # DORA and pipeline metrics
python scripts/feedback.py --observed-p95-ms 80 # REQ-013 latency feedback
./scripts/demo.sh                               # end-to-end change-impact demo
```

The demo script builds its own temporary repository, exercises validation,
impact, selective tests, the thread, baselines, and the negative demos, and
exits non-zero if any expected step fails. See [Demo](demo.md).

The requirements, architecture, RTM, test, security, impact, metrics, and
summary pages are produced under `docs/generated/` by `mbse generate docs` and
`mbse report` (run by `make site`); the digital-thread page is produced by
`mbse thread build`. The other generated artifacts are produced by
`mbse generate all`.
