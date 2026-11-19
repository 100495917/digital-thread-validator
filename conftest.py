"""Pytest plugin that records requirement-tagged test outcomes.

The plugin maps collected test node IDs to the requirement IDs named by
``@pytest.mark.req(...)`` markers and writes the call-phase outcomes to
``build/reports/req_results.json``.  The file feeds the requirements coverage
report (``mbse reqcov``) and the traceability matrix.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from pathlib import Path

_REPORT_DIRECTORY = Path("build") / "reports"
_RESULTS_FILE = "req_results.json"

_node_requirements: dict[str, tuple[str, ...]] = {}
_results: dict[str, list[dict[str, object]]] = {}
_recorded: set[tuple[str, str]] = set()
_write_enabled = False


def _report_directory(config) -> Path:
    """Return ``build/reports`` under the pytest root directory."""
    return Path(str(config.rootpath)) / _REPORT_DIRECTORY


def _writing_enabled(config) -> bool:
    """Return whether this process should write the results file."""
    if config.getoption("collectonly", False):
        return False
    if os.environ.get("PYTEST_XDIST_WORKER"):
        return False
    try:
        numprocesses = config.getoption("numprocesses")
    except (AttributeError, ValueError):
        numprocesses = None
    return not numprocesses


def _marker_ids(marker) -> Iterable[str]:
    """Yield the requirement IDs declared by one ``req`` marker."""
    for arg in marker.args:
        if isinstance(arg, str):
            value = arg.strip()
            if value:
                yield value
        elif isinstance(arg, (list, tuple, set, frozenset)):
            for item in arg:
                if isinstance(item, str):
                    value = item.strip()
                    if value:
                        yield value


def _outcome(report) -> str | None:
    """Return the reported outcome for a test, or ``None`` when not final."""
    if report.when == "call":
        if report.passed:
            return "passed"
        if report.failed:
            return "failed"
        if report.skipped:
            return "skipped"
    elif report.when == "setup" and report.skipped:
        return "skipped"
    return None


def pytest_configure(config) -> None:
    """Create the report directory and reset plugin state for this session."""
    global _write_enabled
    _node_requirements.clear()
    _results.clear()
    _recorded.clear()
    _write_enabled = _writing_enabled(config)
    _report_directory(config).mkdir(parents=True, exist_ok=True)


def pytest_collection_finish(session) -> None:
    """Map each collected test node ID to its requirement marker IDs."""
    for item in session.items:
        ids: set[str] = set()
        for marker in item.iter_markers(name="req"):
            ids.update(_marker_ids(marker))
        _node_requirements[item.nodeid] = tuple(sorted(ids))


def pytest_runtest_logreport(report) -> None:
    """Record the call-phase outcome and duration for requirement tests."""
    if not _write_enabled:
        return

    outcome = _outcome(report)
    if outcome is None:
        return

    key = (report.nodeid, outcome)
    if key in _recorded:
        return
    _recorded.add(key)

    duration = round(float(report.duration), 6)
    for requirement_id in _node_requirements.get(report.nodeid, ()):
        _results.setdefault(requirement_id, []).append(
            {
                "test": report.nodeid,
                "outcome": outcome,
                "duration": duration,
            }
        )


def pytest_sessionfinish(session, exitstatus) -> None:
    """Write the deterministic requirement-results JSON file."""
    if not _write_enabled:
        return

    payload = {
        requirement_id: sorted(
            entries,
            key=lambda entry: (
                str(entry["test"]),
                str(entry["outcome"]),
                float(entry["duration"]),
            ),
        )
        for requirement_id, entries in sorted(_results.items())
    }
    directory = _report_directory(session.config)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / _RESULTS_FILE
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
