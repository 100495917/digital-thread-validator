# Demo: requirement change, impact, failure, and release

`scripts/demo.sh` reproduces the Phase 15 scenario from `PLAN.md` end to end
without GitHub and without touching the working checkout. It copies the
repository into a temporary directory, creates a fresh Git history there, and
walks through a requirement change, selective-test failure, digital-thread
staleness, a controller fix, a second baseline, a changelog, DORA metrics, and
the aggregate report. It then runs four negative demos and removes the
temporary tree.

The demo is the shortest way to see the whole digital thread in motion: the
requirement, model, source, tests, thread, reports, and baselines are all
ordinary files that can be inspected and diffed.

## Prerequisites

- Linux or macOS with `bash`, `git`, and `tar`.
- Python 3.11 or newer.
- The project installed in the active environment so `mbse` is on `PATH`:

  ```bash
  python -m venv .venv
  source .venv/bin/activate
  python -m pip install -e '.[dev]'
  ```

- `pytest` available through the same interpreter. The script uses
  `${PYTHON:-python}` for `python -m pytest` and
  `python -m mbse.select_tests`; set `PYTHON` to use another interpreter.
- Optional: `pip-audit` for the vulnerable-dependency demo. When it is missing,
  or when it cannot reach an advisory database, the script prints an explicit
  `SKIP` line instead of failing.

The main scenario needs no GitHub credentials, no running services, and no
network. The fake-secret demo calls the gitleaks stage directly
(`mbse.security.scan_secrets`), which uses the local gitleaks binary when
available and the built-in Python fallback otherwise; neither needs network.
The only step that may need an advisory database is the explicit `pip-audit`
CVE demo, which prints `SKIP` when it cannot reach one.

## Run it

From the repository root:

```bash
./scripts/demo.sh
```

The script exits `0` only when every required step behaved as expected. It
exits `1` if an expected success fails, or if a negative demo that should fail
unexpectedly succeeds. A missing optional tool counts as `SKIP`, not `FAIL`.

Output is deliberately explicit:

```text
=== Validate baseline artifacts ===
validated 13 requirement file(s), 1 model file(s), 0 error(s), 0 warning(s)
PASS  Validate baseline artifacts

=== Negative demo: fake AWS access key (gitleaks) ===
...
PASS  gitleaks rejected the fake AWS key
```

The temporary tree is removed by an `EXIT` trap, including after a failure.

## Step-by-step expected output

Counts, commit SHAs, node counts, and the exact set of selected test IDs vary
with the repository contents. The important lines and assertions are stable.

### 1. Isolated baseline

The script copies everything except `.git`, `.venv`, `build`, `site`, `docs`,
`reports`, caches, bytecode, and egg metadata. It removes the copied
`digital_thread/` history so the baseline thread is generated locally, then
runs `git init`, configures a local author, and makes the initial commit.

### 2. Freeze baseline `v1.0.0`

```text
=== Validate baseline artifacts ===
validated 13 requirement file(s), 1 model file(s), 0 error(s), 0 warning(s)
PASS  Validate baseline artifacts

=== Check baseline traceability ===
traceability coverage: 100.0%
verification coverage: 100.0%
PASS  Check baseline traceability
```

The requirement tests pass, the RTM is written by `mbse trace rtm`, and
`mbse thread update` records the first digital-thread snapshot. `mbse baseline
freeze v1.0.0` prints:

```text
baselines/baseline-v1.0.0.json
```

The baseline JSON contains the SHA-256 hash of every requirement, model,
source, and test file, the current RTM rows, and the current digital-thread
snapshot. The script commits the baseline and creates the Git tag `v1.0.0`.

### 3. Change REQ-003 on a branch

The script creates `demo/req-003`, changes the activation threshold in
`requirements/REQ-003.yaml` from `0.5` to `0.3`, adds
`tests/requirements/test_req_003_threshold.py`, and commits with:

```text
feat(REQ-003): tighten heating activation threshold to 0.3 C
```

`mbse validate all` still passes: the requirement remains measurable and
unambiguous.

### 4. Refresh the thread and observe stale tests

`mbse thread update` refreshes the graph so the new test is available to impact
analysis. It prints a summary such as:

```text
nodes: <n>, edges: <m>
added: <n>, removed: <m>, modified: <k>, stale: <s>
digital_thread/thread.json
digital_thread/history/<sha>.json
build/reports/thread_diff.md
```

Here `stale` is greater than zero: the existing tests that still verify
REQ-003 were not modified even though their upstream requirement changed.
`build/reports/thread_diff.md` lists those test nodes under `## Stale nodes`.

### 5. Analyse impact from `v1.0.0`

```text
=== Analyse impact from v1.0.0 ===
changed_files: 2
directly_changed: 2
impacted: <n>
needs_review: <n>
needs_retest: <n>
risk: <low|medium>
build/reports/impact.json
build/reports/impact.md
build/reports/rtm_diff.md
PASS  Analyse impact from v1.0.0
```

The changed files are `requirements/REQ-003.yaml` and the new demo test. The
report links REQ-003 to the controller model element, the controller source
file, and the tests that verify or exercise it. `mbse thread query
--downstream REQ-003` prints those downstream nodes, including
`tests/requirements/test_req_003_threshold.py::test_req_003_threshold_updated`.

### 6. Selective tests fail on purpose

`python -m mbse.select_tests` prints the `needs_retest` node IDs on one line.
The script runs exactly those IDs with pytest. The new test imports
`HYSTERESIS_DELTA_C` from the still-unfixed controller and asserts that it is
`0.3`, so the run fails while the pre-existing tests pass:

```text
FAILED tests/requirements/test_req_003_threshold.py::test_req_003_threshold_updated
...
PASS  Selective test run failed as expected
```

The repository pytest plugin writes `build/reports/req_results.json`. The
script checks that the failure is attached to `REQ-003`:

```text
REQ-003 failed tests:
  tests/requirements/test_req_003_threshold.py::test_req_003_threshold_updated
PASS  Failure is mapped to REQ-003
```

### 7. Fix and go green

The script changes `HYSTERESIS_DELTA_C` to `0.3` in
`src/thermostat/controller.py`. Because the throwaway demo tree has existing
boundary tests that encode the old `0.5` value, it updates those boundary
expectations too; the real checkout is never modified. It commits:

```text
fix(REQ-003): align controller and tests with the 0.3 C threshold
```

Then it runs the validation, the requirement suite, and the previously selected
tests. All pass. `mbse thread update` reports `stale: 0`, clearing the
staleness flags from the previous snapshot. A second impact analysis shows the
fix together with the requirement change, and:

```text
mbse commits check --range v1.0.0..HEAD --strict
```

reports no findings because both commits are conventional and reference
`REQ-003`.

### 8. Release `v1.1.0`

```text
=== Freeze baseline v1.1.0 ===
baselines/baseline-v1.1.0.json
PASS  Freeze baseline v1.1.0

=== Compare baselines v1.0.0 and v1.1.0 ===
...
PASS  Compare baselines v1.0.0 and v1.1.0
```

`mbse baseline diff v1.0.0 v1.1.0` prints artifact, RTM, and thread change
counts and writes `build/reports/baseline_diff.json` plus
`build/reports/baseline_diff.md`. The diff shows, at minimum:

- `requirements/REQ-003.yaml` and `src/thermostat/controller.py` changed;
- the new test file was added and the existing controller tests changed;
- REQ-003's RTM row changed while unaffected requirements did not;
- the digital-thread nodes for REQ-003, the controller, and the affected tests
  changed or were added.

The script commits the `v1.1.0` baseline, tags it, generates
`build/reports/changelog.md`, writes `build/reports/metrics.json` with
`mbse metrics`, and runs `mbse report`:

```text
status: pass
build/reports/summary.json
build/reports/summary.md
...
PASS  Aggregate the pipeline report
```

### 9. Negative demos

Each negative demo creates one temporary file, asserts the expected failure,
prints `PASS`, and removes the file.

| Negative demo | Expected evidence |
|---|---|
| Ambiguous requirement `REQ-014` (`"The system shall respond quickly."`, type `performance`) | `mbse validate all` exits non-zero with `RQ-003` (ambiguous wording) and `RQ-004` (performance requirement without a measurable value) |
| Valid requirement `REQ-015` with no model element, code tag, or test | `mbse trace check` exits non-zero with `TRC-001` (no satisfying model element) and `TRC-003` (approved `verification: test` requirement with no test) |
| Fake AWS access key written at runtime to `demo-secrets.txt` | The gitleaks stage (`mbse.security.scan_secrets`) reports `gitleaks: failed`; the literal key is constructed at runtime so the demo script itself is not a finding |
| `pyyaml==5.3` in a temporary requirements file | `pip-audit -r demo-cve-requirements.txt --no-deps` exits non-zero with a `PYSEC`/`CVE` identifier for PyYAML; if `pip-audit` is missing or the advisory database is unreachable, the script prints `SKIP` |

The final section prints the impacted artifacts from the last impact report,
grouped by `directly_changed`, `impacted`, `needs_review`, and `needs_retest`,
followed by the `PASS`/`FAIL`/`SKIP` totals.

## Local transcript

The transcript below is an abridged, representative run; paths, SHAs, node
counts, and selected test IDs depend on the checkout. Capture your own with:

```bash
./scripts/demo.sh 2>&1 | tee /tmp/digital-thread-demo.log
```

```text
=== Creating an isolated copy of the repository ===
Working tree: /tmp/dtv-demo.XXXXXXXX/project

=== Initialising a fresh Git repository ===
PASS  Created isolated Git history

=== Validate baseline artifacts ===
validated 13 requirement file(s), 1 model file(s), 0 error(s), 0 warning(s)
PASS  Validate baseline artifacts

=== Check baseline traceability ===
traceability coverage: 100.0%
verification coverage: 100.0%
PASS  Check baseline traceability

=== Run baseline requirement tests ===
... 13 passed ...
PASS  Run baseline requirement tests

=== Record the baseline digital thread ===
nodes: <n>, edges: <m>
...
PASS  Record the baseline digital thread

=== Freeze baseline v1.0.0 ===
baselines/baseline-v1.0.0.json
PASS  Freeze baseline v1.0.0

=== Validate the changed requirement ===
validated 13 requirement file(s), 1 model file(s), 0 error(s), 0 warning(s)
PASS  Validate the changed requirement

=== Refresh the digital thread and expose staleness ===
nodes: <n>, edges: <m>
added: <n>, removed: <m>, modified: <k>, stale: <s>
...
PASS  Updated digital thread after the requirement change
PASS  Staleness flags the unaffected REQ-003 tests

=== Analyse impact from v1.0.0 ===
changed_files: 2
directly_changed: 2
impacted: <n>
needs_review: <n>
needs_retest: <n>
risk: <low|medium>
build/reports/impact.json
build/reports/impact.md
build/reports/rtm_diff.md
PASS  Analyse impact from v1.0.0

=== Show downstream artifacts of REQ-003 ===
ModelElement BLK-controller
ModelElement BLK-heater
CodeModule src/thermostat/controller.py
Test tests/requirements/test_req_003_threshold.py::test_req_003_threshold_updated
...
PASS  Show downstream artifacts of REQ-003

=== Selective test selection ===
selected: tests/requirements/test_req_003_threshold.py::test_req_003_threshold_updated ...
PASS  The new REQ-003 test is selected

=== Run the selected tests (expected failure) ===
FAILED tests/requirements/test_req_003_threshold.py::test_req_003_threshold_updated
...
PASS  Selective test run failed as expected

=== Check req_results.json maps the failure to REQ-003 ===
REQ-003 failed tests:
  tests/requirements/test_req_003_threshold.py::test_req_003_threshold_updated
PASS  Failure is mapped to REQ-003

=== Fix the controller constant and affected boundary expectations ===
PASS  Committed the controller fix

=== Run requirement and controller tests ===
... passed ...
PASS  Run requirement and controller tests

=== Re-run the previously selected tests (green) ===
... passed ...
PASS  Re-run the previously selected tests (green)

=== Refresh the digital thread after the fix ===
...
stale: 0
PASS  Refresh the digital thread after the fix
PASS  Staleness flags cleared after the fix

=== Freeze baseline v1.1.0 ===
baselines/baseline-v1.1.0.json
PASS  Freeze baseline v1.1.0

=== Compare baselines v1.0.0 and v1.1.0 ===
...
PASS  Compare baselines v1.0.0 and v1.1.0

=== Negative demo: ambiguous requirement (RQ-003/RQ-004) ===
requirements/REQ-014.yaml: RQ-003 error: ambiguous term 'quickly' in text
requirements/REQ-014.yaml: RQ-004 error: performance requirement lacks a measurable value with a unit
PASS  Ambiguous requirement rejected with RQ-003 and RQ-004

=== Negative demo: fake AWS access key (gitleaks) ===
gitleaks: failed (1 finding(s))
demo-secrets.txt:1: SEC-SECRET-AWS critical: possible AWS access key
PASS  gitleaks rejected the fake AWS key

=== Negative demo: vulnerable dependency (pip-audit) ===
Found 1 known vulnerability in 1 package
...
PASS  pip-audit reported the PyYAML vulnerability

=== Demo summary ===
PASS=<n> FAIL=0 SKIP=<n>
Expected failures exercised: ...
```

The exact number of `PASS` lines can grow when additional checks are added;
the acceptance condition is `FAIL=0`.

## Reproducing the same scenario on GitHub

The local script and the GitHub workflows exercise the same artifacts. To
reproduce the full CI/release path:

1. **Branch and pull request.** Push the branch containing the REQ-003 change
   and the failing demo test, then open a pull request against `main`. The
   `.github/workflows/ci.yml` pipeline runs validation, traceability, artifact
   generation, tests, security, thread update, impact analysis, and report
   aggregation. `.github/workflows/pr-impact.yml` posts or updates one sticky
   comment with `build/reports/impact.md`, including the RTM diff and thread
   diff.
2. **Required checks.** Configure `lint-validate`, `trace-check`, `test`, and
   `security` as required status checks on `main`; the PR stays blocked until
   those jobs are green.
3. **First failure.** The new demo test fails in the `test` job, and
   `req_results.json` maps it to REQ-003. After the fix commit, the same jobs
   turn green and the thread update clears staleness.
4. **Merge and Pages.** Merging to `main` triggers
   `.github/workflows/pages.yml`, which rebuilds the thread and reports, runs
   the pipeline, builds the MkDocs site with `--strict`, and deploys it to
   GitHub Pages. The site contains the generated requirements, architecture,
   RTM, test, security, impact, metrics, and summary pages, plus the digital
   thread.
5. **Tag the release.** After the fix is merged, create and push `v1.1.0`:

   ```bash
   git tag v1.1.0
   git push origin v1.1.0
   ```

   `.github/workflows/release.yml` runs the full pipeline for that tag, freezes
   `baselines/baseline-v1.1.0.json`, generates the changelog (the Python
   generator is the fallback when `git-cliff` is unavailable), and creates a
   GitHub Release with the baseline, changelog, RTM CSV, SBOM, summary JSON,
   and thread snapshot attached.
6. **Rollback (optional).** Pick a previous commit-SHA image tag in
   `.github/workflows/rollback.yml`; the workflow redeploys that image through
   Compose and repeats the health and smoke checks.

### Where links are recorded

Do not invent PR, Pages, or Release URLs. After a real run, record the links in
this table in `docs/demo.md`:

| Reproduction artifact | URL |
|---|---|
| Pull request with the failing and fixed commits | _record after opening the PR_ |
| Sticky impact comment | Same PR, comment header `impact-analysis` |
| GitHub Pages site | _record the Pages URL from the repository settings_ |
| GitHub Release `v1.1.0` | _record the release URL after pushing the tag_ |

The workflow logs and uploaded artifacts (`impact-reports`, `test-reports`,
`security-reports`, `pipeline-reports`, `release-assets`, and
`staging-deployment`) are the evidence for the other steps.

## Troubleshooting

- `mbse: command not found`: activate the virtualenv and run
  `python -m pip install -e '.[dev]'`.
- `pytest: command not found`: install the development extras in the same
  environment used for `mbse`.
- `pip-audit` prints `SKIP`: the demo deliberately does not treat an offline
  advisory database as a failure. Run the dependency audit in CI or with
  network access to see the PyYAML finding.
- `gitleaks` is not installed: the gitleaks stage uses its built-in Python
  secret scanner, which detects the same fake AWS key. The negative demo still
  passes.
- The script does not modify your checkout; if it exits early, the temporary
  directory is removed automatically. Set `TMPDIR` to control where the copy is
  created.

## Recorded local run

The repository was exercised end to end after implementation. The abridged
results are:

```text
$ make all
validated 13 requirement file(s), 1 model file(s), 0 error(s), 0 warning(s)
traceability coverage: 100.0%
requirements coverage: 100.0%
nodes: 146, edges: 295
status: pass

$ scripts/demo.sh
...
PASS=36 FAIL=0 SKIP=0
Expected failures exercised: selective REQ-003 test failure,
RQ-003/RQ-004 ambiguity, TRC-001/TRC-003 trace gaps, gitleaks secret,
and pip-audit CVE (or an explicit SKIP when the advisory database is unreachable).
```

The staging image was also built locally and passed the smoke suite:
status 200, unauthenticated update 401, setpoint range 200/422/422,
and p95 3.2 ms against a 100 ms threshold.
