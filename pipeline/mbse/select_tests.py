"""Select the tests that must be re-run for the current impact report.

The impact analysis in :mod:`mbse.impact` writes
``build/reports/impact.json``.  This module turns its ``needs_retest``
classification into a space-separated list suitable for ``pytest`` or a CI
step.  Directly changed test artifacts are always included: a modified test
must run even when the graph traversal did not classify it as retest-needing.
"""

from __future__ import annotations

import json
from pathlib import Path

_IMPACT_REPORT = Path("build") / "reports" / "impact.json"


def _load_report(root: Path) -> dict:
    """Read the impact report, returning ``{}`` when it is unavailable."""
    path = root / _IMPACT_REPORT
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return raw


def _artifacts(report: dict, key: str) -> list[dict]:
    """Return the well-formed artifact entries for one classification."""
    artifacts = report.get("artifacts")
    if not isinstance(artifacts, dict):
        return []
    entries = artifacts.get(key)
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def select_tests(root: Path = Path(".")) -> list[str]:
    """Return the sorted, unique pytest node IDs that must be re-run."""
    root = Path(root)
    report = _load_report(root)

    selected: set[str] = set()
    for entry in _artifacts(report, "needs_retest"):
        if entry.get("type") != "Test":
            continue
        test_id = entry.get("id")
        if isinstance(test_id, str) and test_id:
            selected.add(test_id)

    for entry in _artifacts(report, "directly_changed"):
        if entry.get("type") != "Test":
            continue
        test_id = entry.get("id")
        if isinstance(test_id, str) and test_id:
            selected.add(test_id)

    return sorted(selected)


def main() -> None:
    """Print the selected test IDs on one line, or nothing when none apply."""
    tests = select_tests()
    if tests:
        print(" ".join(tests))


if __name__ == "__main__":
    main()
