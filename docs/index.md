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
- [Decisions](decisions.md) — binding architecture and tooling decisions.
- [Pipeline](pipeline.md) — pipeline stages, commands, and report locations.

## Quick start

```bash
make validate   # validate requirement YAML, the model, and their schemas
make test       # run pytest and write JUnit, coverage, and req-result reports
make trace      # check requirement-to-model-to-code-to-test traceability
make site       # generate docs and build the MkDocs site with --strict
```

The generated documentation pages are produced by `mbse generate docs` (run by
`make site`); the other generated artifacts are produced by `mbse generate all`.
