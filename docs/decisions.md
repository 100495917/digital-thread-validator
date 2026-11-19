# Architecture Decisions

This document records the architectural and tooling decisions for the
digital-thread-validator project. Decisions here are binding: do not re-open
them unless a hard blocker appears. When a decision changes, edit this file and
explain the reason.

## Decisions from the project plan

| Topic | Decision |
|---|---|
| CI/CD | GitHub Actions |
| Language for tooling | Python 3.11+ |
| Requirements format | One YAML file per requirement in `requirements/` |
| Model format | YAML "system model" in `models/` (blocks, interfaces, behaviors) validated by a JSON Schema. PlantUML diagrams are *generated* from the model |
| Digital thread store | NetworkX graph serialized to JSON at `digital_thread/thread.json`. Optional Neo4j export is a stretch goal |
| Test framework | pytest with a custom `req` marker |
| Docs / site | MkDocs (Material) published to GitHub Pages |
| Security | Gitleaks, Bandit, Semgrep, pip-audit, Trivy, Checkov (for IaC), SBOM via CycloneDX |
| Deploy | Docker + Docker Compose (staging), health-check smoke test |
| Example system | Smart Thermostat Controller (small, easy to trace) |

## Digital thread store

The digital thread is a directed graph of requirements, model elements, code
tags, tests, and generated artifacts. It is built with NetworkX and serialized
to JSON at `digital_thread/thread.json`.

Rationale:

- JSON is diffable, reviewable, and committed with the repository.
- No external database or service is required for CI or local development.
- NetworkX is a pure-Python dependency available offline.
- A Neo4j export, if ever needed, remains an optional add-on rather than a
  requirement.

Snapshots are written to `digital_thread/history/<sha>.json`, one per pipeline
run.

## Deterministic output

All generated artifacts must be deterministic:

- Sort collections (requirements by ID, model elements by name or ID, graph
  nodes and edges by a stable key) before emission.
- Do not embed absolute paths, machine names, or environment-specific values in
  generated files.
- Serialize JSON with a stable key order and stable indentation.
- Given identical inputs, regenerating must produce byte-identical output, so a
  clean `git diff` is the check that generated files are current.

Rationale: determinism makes generated artifacts reviewable, prevents spurious
diffs, and lets CI fail when generation is stale.

## No timestamps in generated files

Generated artifacts must not contain timestamps (build time, generation time,
"last updated", or any equivalent).

Rationale: timestamps break determinism and produce a diff on every run. When a
timestamp-like value is genuinely needed for provenance, it belongs in the
commit metadata, the pipeline run, or a file name, never in generated content.

## Tooling fallbacks

If a tool cannot be installed or run in an offline environment, implement the
check as a minimal Python fallback and record the fallback in this document.
Fallbacks must fail closed where the real tool would: a check that cannot run
must not silently pass.

### Phase 1: repo-local pre-commit hooks instead of remote hook repos

The Phase 1 pre-commit configuration uses only `repo: local` hooks that invoke
tools available in the development environment. It does not reference remote
hook repositories (for example, `https://github.com/pre-commit/pre-commit-hooks`
or `https://github.com/astral-sh/ruff-pre-commit`).

Rationale: remote hook repositories require network access on first install,
which is unavailable offline. Local hooks keep `pre-commit run --all-files`
working without fetching from GitHub, and they can be retargeted to published
hook repositories once CI has network access.

### Phase 1: Gitleaks only when the binary is present

The Phase 1 secret-scanning hook runs Gitleaks only when a `gitleaks` binary is
available on the local machine. It does not download or vendor the binary.

Rationale: the Gitleaks binary is not guaranteed to be installed offline. The
hook must not fail merely because the tool is absent, but it must also not
pretend a scan happened. Full, always-on secret scanning is enforced in CI in
Phase 7. Once CI provides the binary, the same check runs unconditionally there.

### Phase 1: Markdown linting via markdownlint-cli (npm)

Markdown is linted with `markdownlint-cli` from npm rather than the Python
package `pymarkdownlnt`. The latter pulls in `pyjson5`, which has no buildable
wheel on the development interpreter (Python 3.15) and therefore breaks
`pip install -e .[dev]`.

Rationale: PLAN.md explicitly allows either tool. Node is available on the
development machine and in the CI runner. The check is wired into pre-commit
and CI in later phases, not into the Python dev extras.

### Phase 1: Python 3.11+ compatibility despite the development machine

The project targets Python 3.11+ even though the development machine may run a
newer interpreter (for example, 3.15). Code and configuration must not use
syntax or APIs unavailable in 3.11.

Rationale: CI and course evaluation environments pin 3.11. Compatibility is
enforced by running tests in CI on the supported interpreter and by avoiding
newer-only features in the tooling.

### Phase 5: Graphviz for diagram rendering when PlantUML is absent

Diagram sources are generated as PlantUML (`.puml`) and Graphviz (`.dot`).
When the `dot` binary is available, `mbse generate diagrams` renders the block
diagram to SVG; otherwise only the sources are written and the documentation
embeds the equivalent Mermaid diagram.

Rationale: PLAN.md allows PlantUML or Graphviz. PlantUML requires Java plus a
jar, while Graphviz is commonly installed and is present on the development
machine.

### Phase 7: Security scanners degrade to Python fallbacks locally

Gitleaks, Semgrep, Trivy, and Checkov may be absent from a developer machine.
`mbse security` reports those tools as `unavailable` with a note, and CI runs
the real tools. Secret scanning always has a Python fallback so a seeded
credential fails locally as well.

`pip-audit` JSON does not expose a reliable severity for every advisory, so
every reported vulnerability is treated as high severity for the gate. This is
stricter than the real severity, which is acceptable for a fail-closed gate.

Rationale: the local environment must be usable offline without pretending a
scan ran, and CI remains the authority for tool-backed checks.
