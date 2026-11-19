#!/usr/bin/env bash
# End-to-end, offline demo for the digital-thread-validator pipeline.
#
# The script copies the repository (without generated output and Git history)
# into a temporary directory, creates a fresh Git repository there, and runs
# the change-impact scenario from PLAN.md Phase 15.  It never modifies the
# checkout it is launched from.
#
# Usage:
#   scripts/demo.sh
#
# Required on PATH:
#   mbse, python, pytest, git
#
# Optional:
#   pip-audit (the CVE negative demo is skipped when it is unavailable or
#   unable to reach an advisory database).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python}"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/dtv-demo.XXXXXX")"
PROJECT_DIR="$TMP_DIR/project"

PASS=0
FAIL=0
SKIP=0

cleanup() {
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT

pass() {
    printf 'PASS  %s\n' "$*"
    PASS=$((PASS + 1))
}

fail() {
    printf 'FAIL  %s\n' "$*" >&2
    FAIL=$((FAIL + 1))
}

skip() {
    printf 'SKIP  %s\n' "$*"
    SKIP=$((SKIP + 1))
}

section() {
    printf '\n=== %s ===\n' "$*"
}

finish() {
    section "Demo summary"
    printf 'PASS=%d FAIL=%d SKIP=%d\n' "$PASS" "$FAIL" "$SKIP"
    printf '%s\n' \
        "Expected failures exercised: selective REQ-003 test failure," \
        "RQ-003/RQ-004 ambiguity, TRC-001/TRC-003 trace gaps, gitleaks secret," \
        "and pip-audit CVE (or an explicit SKIP when the advisory database is unreachable)."
    if ((FAIL > 0)); then
        exit 1
    fi
    exit 0
}

run_required() {
    local label="$1"
    shift
    section "$label"
    if "$@"; then
        pass "$label"
    else
        fail "$label"
        finish
    fi
}

usage_error() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 2
}

command -v git >/dev/null 2>&1 || usage_error "git is required"
command -v mbse >/dev/null 2>&1 || usage_error \
    "mbse is not on PATH; activate the project virtualenv and run pip install -e '.[dev]'"
command -v "$PYTHON" >/dev/null 2>&1 || usage_error "$PYTHON is required"
"$PYTHON" -m pytest --version >/dev/null 2>&1 || usage_error \
    "pytest is not available for $PYTHON; install the development dependencies"

section "Creating an isolated copy of the repository"
mkdir -p "$PROJECT_DIR"
tar -C "$REPO_ROOT" \
    --exclude=./.git \
    --exclude=./.venv \
    --exclude=./build \
    --exclude=./site \
    --exclude=./docs \
    --exclude=./reports \
    --exclude=./.pytest_cache \
    --exclude=./.ruff_cache \
    --exclude=./.coverage \
    --exclude='*/__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.egg-info' \
    -cf - . | tar -C "$PROJECT_DIR" -xf -
cd "$PROJECT_DIR"
# Start from a clean thread history so the baseline is generated locally.
rm -rf digital_thread
printf 'Working tree: %s\n' "$PROJECT_DIR"

section "Initialising a fresh Git repository"
git init -q
git config user.name "Digital Thread Demo"
git config user.email "demo@example.invalid"
git add -A
git commit -q -m "chore: import demo baseline (REQ-001..REQ-013)"
pass "Created isolated Git history"

# ---------------------------------------------------------------------------
# Baseline v1.0.0
# ---------------------------------------------------------------------------

run_required "Validate baseline artifacts" mbse validate all
run_required "Check baseline traceability" mbse trace check
run_required "Run baseline requirement tests" "$PYTHON" -m pytest tests/requirements
run_required "Build the baseline RTM" mbse trace rtm
run_required "Record the baseline digital thread" mbse thread update
run_required "Freeze baseline v1.0.0" mbse baseline freeze v1.0.0

git add baselines
git commit -q -m "chore(release): freeze baseline v1.0.0"
git tag v1.0.0
pass "Committed and tagged baseline v1.0.0"

# ---------------------------------------------------------------------------
# Change REQ-003 on a branch
# ---------------------------------------------------------------------------

section "Creating the demo branch and changing REQ-003"
git checkout -q -b demo/req-003
sed -i 's/0\.5/0.3/' requirements/REQ-003.yaml

cat > tests/requirements/test_req_003_threshold.py <<'PY'
"""Demo-only regression test for the tightened REQ-003 hysteresis threshold."""

from __future__ import annotations

from pathlib import Path

import pytest

from thermostat.controller import HYSTERESIS_DELTA_C


@pytest.mark.req("REQ-003")
def test_req_003_threshold_updated() -> None:
    text = Path("requirements/REQ-003.yaml").read_text(encoding="utf-8")
    assert "0.3" in text
    assert HYSTERESIS_DELTA_C == 0.3
PY

git add requirements/REQ-003.yaml tests/requirements/test_req_003_threshold.py
git commit -q -m "feat(REQ-003): tighten heating activation threshold to 0.3 C"
pass "Committed the requirement change and demo test"

run_required "Validate the changed requirement" mbse validate all

# The thread must be refreshed before impact analysis so the new test and the
# changed requirement are present in the graph used for selective selection.
section "Refresh the digital thread and expose staleness"
if THREAD_OUTPUT="$(mbse thread update 2>&1)"; then
    printf '%s\n' "$THREAD_OUTPUT"
    pass "Updated digital thread after the requirement change"
else
    printf '%s\n' "$THREAD_OUTPUT"
    fail "Digital thread update after the requirement change"
    finish
fi

STALE_SECTION="$(sed -n '/^## Stale nodes/,$p' build/reports/thread_diff.md || true)"
if printf '%s\n' "$THREAD_OUTPUT" | grep -Eq 'stale: [1-9]' \
    && printf '%s\n' "$STALE_SECTION" | grep -q 'tests/'; then
    pass "Staleness flags the unaffected REQ-003 tests"
else
    fail "Expected stale REQ-003 test nodes in build/reports/thread_diff.md"
    finish
fi

run_required "Analyse impact from v1.0.0" mbse impact --base v1.0.0 --head HEAD
run_required "Show downstream artifacts of REQ-003" \
    mbse thread query --downstream REQ-003

# ---------------------------------------------------------------------------
# Selective tests deliberately fail
# ---------------------------------------------------------------------------

section "Selective test selection"
SELECTED="$("$PYTHON" -m mbse.select_tests)"
printf 'selected: %s\n' "$SELECTED"
if [[ -z "$SELECTED" ]]; then
    fail "select_tests returned no tests"
    finish
fi
read -r -a TEST_IDS <<<"$SELECTED"

if [[ " $SELECTED " == *"test_req_003_threshold.py"* ]]; then
    pass "The new REQ-003 test is selected"
else
    fail "The new REQ-003 test was not selected"
    finish
fi

section "Run the selected tests (expected failure)"
set +e
SELECTIVE_OUTPUT="$("$PYTHON" -m pytest "${TEST_IDS[@]}" 2>&1)"
SELECTIVE_STATUS=$?
set -e
printf '%s\n' "$SELECTIVE_OUTPUT"
if ((SELECTIVE_STATUS != 0)); then
    pass "Selective test run failed as expected"
else
    fail "Selective test run unexpectedly passed"
    finish
fi

section "Check req_results.json maps the failure to REQ-003"
if "$PYTHON" - <<'PY'
import json
from pathlib import Path

data = json.loads(Path("build/reports/req_results.json").read_text(encoding="utf-8"))
entries = data.get("REQ-003", [])
failed = [entry for entry in entries if entry.get("outcome") == "failed"]
if failed:
    print("REQ-003 failed tests:")
    for entry in failed:
        print(f"  {entry['test']}")
    raise SystemExit(0)
print("REQ-003 has no failed test result")
raise SystemExit(1)
PY
then
    pass "Failure is mapped to REQ-003"
else
    fail "Failure mapping in build/reports/req_results.json"
fi

# ---------------------------------------------------------------------------
# Fix the controller and go green
# ---------------------------------------------------------------------------

section "Fix the controller constant and affected boundary expectations"
sed -i 's/^HYSTERESIS_DELTA_C = 0.5$/HYSTERESIS_DELTA_C = 0.3/' \
    src/thermostat/controller.py

# Keep the demo copy internally consistent: the existing boundary tests encode
# the old 0.5 C hysteresis and are updated in the throwaway tree only.
sed -i \
    -e 's/controller.update(21\.4) is True/controller.update(21.2) is True/' \
    -e 's/controller.update(21\.5) is False/controller.update(21.4) is False/' \
    -e 's/controller.update(20\.5) is False/controller.update(20.7) is False/' \
    tests/requirements/test_requirements.py
sed -i \
    -e 's/assert HYSTERESIS_DELTA_C == 0\.5/assert HYSTERESIS_DELTA_C == 0.3/' \
    -e 's/controller.update(20\.5) is False/controller.update(20.7) is False/' \
    -e 's/controller.update(21\.499) is True/controller.update(21.299) is True/' \
    -e 's/controller.update(21\.4) is True/controller.update(21.2) is True/' \
    -e 's/controller.update(20\.6) is False/controller.update(20.7) is False/' \
    tests/unit/test_controller.py

# Touch the demo test so its thread node reflects the post-fix review; this is
# what clears staleness for tests that exercise the changed controller module.
printf '\n# Regression coverage for the v1.1.0 threshold.\n' \
    >> tests/requirements/test_req_003_threshold.py

git add src/thermostat/controller.py \
    tests/requirements/test_requirements.py \
    tests/requirements/test_req_003_threshold.py \
    tests/unit/test_controller.py
git commit -q -m "fix(REQ-003): align controller and tests with the 0.3 C threshold"
pass "Committed the controller fix"

run_required "Validate the fixed tree" mbse validate all
run_required "Run requirement and controller tests" \
    "$PYTHON" -m pytest tests/requirements tests/unit/test_controller.py
run_required "Re-run the previously selected tests (green)" \
    "$PYTHON" -m pytest "${TEST_IDS[@]}"

section "Refresh the digital thread after the fix"
if FIXED_THREAD_OUTPUT="$(mbse thread update 2>&1)"; then
    printf '%s\n' "$FIXED_THREAD_OUTPUT"
    if printf '%s\n' "$FIXED_THREAD_OUTPUT" | grep -Eq 'stale: 0([^0-9]|$)'; then
        pass "Staleness flags cleared after the fix"
    else
        fail "Expected stale: 0 after the fix"
    fi
else
    printf '%s\n' "$FIXED_THREAD_OUTPUT"
    fail "Digital thread update after the fix"
    finish
fi

run_required "Re-run impact analysis after the fix" \
    mbse impact --base v1.0.0 --head HEAD
run_required "Check conventional commits on the demo branch" \
    mbse commits check --range v1.0.0..HEAD --strict
run_required "Rebuild the RTM after the fix" mbse trace rtm

# ---------------------------------------------------------------------------
# Release v1.1.0
# ---------------------------------------------------------------------------

run_required "Freeze baseline v1.1.0" mbse baseline freeze v1.1.0
git add baselines
git commit -q -m "chore(release): freeze baseline v1.1.0"
git tag v1.1.0
pass "Committed and tagged baseline v1.1.0"

run_required "Compare baselines v1.0.0 and v1.1.0" \
    mbse baseline diff v1.0.0 v1.1.0
run_required "Generate the changelog" \
    mbse changelog --version v1.1.0 --output build/reports/changelog.md
run_required "Compute DORA metrics" mbse metrics
run_required "Aggregate the pipeline report" mbse report

# ---------------------------------------------------------------------------
# Negative demos
# ---------------------------------------------------------------------------

section "Negative demo: ambiguous requirement (RQ-003/RQ-004)"
cat > requirements/REQ-014.yaml <<'YAML'
id: REQ-014
title: "Fast response"
text: "The system shall respond quickly."
type: performance
priority: medium
owner: team-performance
verification: test
status: approved
rationale: "Demo-only ambiguous requirement."
YAML

set +e
AMBIGUOUS_OUTPUT="$(mbse validate all 2>&1)"
AMBIGUOUS_STATUS=$?
set -e
printf '%s\n' "$AMBIGUOUS_OUTPUT"
if ((AMBIGUOUS_STATUS != 0)) \
    && printf '%s\n' "$AMBIGUOUS_OUTPUT" | grep -q 'RQ-003' \
    && printf '%s\n' "$AMBIGUOUS_OUTPUT" | grep -q 'RQ-004'; then
    pass "Ambiguous requirement rejected with RQ-003 and RQ-004"
else
    fail "Expected RQ-003 and RQ-004 for the ambiguous requirement"
fi
rm -f requirements/REQ-014.yaml

section "Negative demo: valid requirement with no model or test (TRC-001/TRC-003)"
cat > requirements/REQ-015.yaml <<'YAML'
id: REQ-015
title: "Heartbeat signal"
text: "The system shall emit a heartbeat every 10 seconds."
type: functional
priority: low
owner: team-control
verification: test
status: approved
rationale: "Demo-only requirement without a model allocation or test."
YAML

set +e
TRACE_OUTPUT="$(mbse trace check 2>&1)"
TRACE_STATUS=$?
set -e
printf '%s\n' "$TRACE_OUTPUT"
if ((TRACE_STATUS != 0)) \
    && printf '%s\n' "$TRACE_OUTPUT" | grep -q 'TRC-001' \
    && printf '%s\n' "$TRACE_OUTPUT" | grep -q 'TRC-003'; then
    pass "Untraced requirement rejected with TRC-001 and TRC-003"
else
    fail "Expected TRC-001 and TRC-003 for the untraced requirement"
fi
rm -f requirements/REQ-015.yaml

section "Negative demo: fake AWS access key (gitleaks)"
# Build the literal at runtime so the demo script itself is not a finding.
FAKE_AWS_KEY="AKIA$(printf 'IOSFODNN7EXAMPLE')"
printf 'aws_access_key_id = "%s"\n' "$FAKE_AWS_KEY" > demo-secrets.txt
set +e
SECURITY_OUTPUT="$("$PYTHON" - <<'PY'
from pathlib import Path

from mbse.security import scan_secrets

result = scan_secrets(Path("."))
print(f"gitleaks: {result.status} ({len(result.findings)} finding(s))")
for finding in result.findings:
    print(f"{finding.path}:{finding.line}: {finding.rule} {finding.severity}: {finding.message}")
raise SystemExit(1 if result.status == "failed" else 0)
PY
)"
SECURITY_STATUS=$?
set -e
printf '%s\n' "$SECURITY_OUTPUT"
if ((SECURITY_STATUS != 0)) \
    && printf '%s\n' "$SECURITY_OUTPUT" | grep -q 'gitleaks: failed'; then
    pass "gitleaks rejected the fake AWS key"
else
    fail "Expected the gitleaks stage to reject the fake AWS key"
fi
rm -f demo-secrets.txt

section "Negative demo: vulnerable dependency (pip-audit)"
if ! command -v pip-audit >/dev/null 2>&1; then
    skip "pip-audit is not installed"
else
    printf 'pyyaml==5.3\n' > demo-cve-requirements.txt
    if command -v timeout >/dev/null 2>&1; then
        set +e
        CVE_OUTPUT="$(timeout 180 pip-audit -r demo-cve-requirements.txt --no-deps 2>&1)"
        CVE_STATUS=$?
        set -e
    else
        set +e
        CVE_OUTPUT="$(pip-audit -r demo-cve-requirements.txt --no-deps 2>&1)"
        CVE_STATUS=$?
        set -e
    fi
    printf '%s\n' "$CVE_OUTPUT"
    rm -f demo-cve-requirements.txt
    if ((CVE_STATUS == 0)); then
        fail "pip-audit unexpectedly accepted pyyaml==5.3"
    elif printf '%s\n' "$CVE_OUTPUT" | grep -Eiq 'PYSEC|CVE-|known vulnerab' \
        && printf '%s\n' "$CVE_OUTPUT" | grep -Eiq 'pyyaml'; then
        pass "pip-audit reported the PyYAML vulnerability"
    else
        skip "pip-audit could not reach an advisory database (offline or network failure)"
    fi
fi

# ---------------------------------------------------------------------------
# Final summary
# ---------------------------------------------------------------------------

section "Impacted artifacts from the final impact report"
if [[ -f build/reports/impact.json ]]; then
    "$PYTHON" - <<'PY'
import json
from pathlib import Path

report = json.loads(Path("build/reports/impact.json").read_text(encoding="utf-8"))
print(f"base: {report.get('base')}")
print(f"head: {report.get('head')}")
print(f"risk: {report.get('risk', {}).get('level', 'unknown')}")
for bucket in ("directly_changed", "impacted", "needs_review", "needs_retest"):
    entries = report.get("artifacts", {}).get(bucket, [])
    print(f"{bucket}: {len(entries)}")
    for entry in entries:
        print(f"  - {entry.get('type')} {entry.get('id')}")
PY
    pass "Printed the impacted artifact summary"
else
    fail "build/reports/impact.json is missing"
fi

finish
