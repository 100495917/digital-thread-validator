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

The requirements, architecture, RTM, test, security, impact, metrics, and
summary pages are produced under `docs/generated/` by `mbse generate docs` and
`mbse report` (run by `make site`); the digital-thread page is produced by
`mbse thread build`. The other generated artifacts are produced by
`mbse generate all`.
