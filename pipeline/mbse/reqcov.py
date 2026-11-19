"""Requirements verification coverage computed from requirement-tagged tests.

For every approved requirement the report states whether at least one
requirement-tagged test passed.  A requirement is *covered* only when it has a
passing test; requirements with only failing or skipped tests, or with no test
results at all, are not covered.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .loaders import load_requirements

DEFAULT_THRESHOLD = 90.0

_REPORT_DIRECTORY = Path("build") / "reports"
_RESULTS_FILE = "req_results.json"
_REPORT_FILE = "reqcov.json"

_PASSED_OUTCOMES = {"passed", "pass", "success", "succeeded"}
_FAILED_OUTCOMES = {"failed", "fail", "error", "errored"}


def _load_results(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Load requirement test results, returning ``{}`` when unavailable."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}

    results: dict[str, list[dict[str, Any]]] = {}
    for requirement_id, entries in raw.items():
        if not isinstance(entries, list):
            continue
        cleaned: list[dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            try:
                duration = float(entry.get("duration", 0.0) or 0.0)
            except (TypeError, ValueError):
                duration = 0.0
            cleaned.append(
                {
                    "test": str(entry.get("test", "")),
                    "outcome": str(entry.get("outcome", "")).strip().lower(),
                    "duration": duration,
                }
            )
        cleaned.sort(
            key=lambda entry: (
                entry["test"],
                entry["outcome"],
                entry["duration"],
            )
        )
        results[str(requirement_id)] = cleaned
    return results


def _count_outcomes(entries: list[dict[str, Any]]) -> tuple[int, int, int]:
    passed = sum(1 for entry in entries if entry["outcome"] in _PASSED_OUTCOMES)
    failed = sum(1 for entry in entries if entry["outcome"] in _FAILED_OUTCOMES)
    skipped = len(entries) - passed - failed
    return passed, failed, skipped


def _requirement_entry(
    requirement_id: str,
    title: str,
    requirement_type: str,
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    passed, failed, skipped = _count_outcomes(entries)
    covered = passed > 0
    if covered:
        status = "passed"
    elif failed:
        status = "failed"
    else:
        status = "missing"
    return {
        "id": requirement_id,
        "title": title,
        "type": requirement_type,
        "status": status,
        "covered": covered,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "tests": entries,
    }


def compute_requirements_coverage(
    root: Path = Path("."),
    results_path: str | Path | None = None,
    threshold: float | None = DEFAULT_THRESHOLD,
) -> dict[str, Any]:
    """Compute per-requirement verification coverage for approved requirements."""
    root = Path(root)
    if results_path is None:
        path = root / _REPORT_DIRECTORY / _RESULTS_FILE
    else:
        path = Path(results_path)
    results = _load_results(path)

    approved = [
        requirement
        for requirement in load_requirements(root)
        if requirement.status.strip().lower() == "approved"
    ]
    approved.sort(key=lambda requirement: requirement.id)

    entries = [
        _requirement_entry(
            requirement.id,
            requirement.title,
            requirement.type,
            results.get(requirement.id, []),
        )
        for requirement in approved
    ]

    total = len(entries)
    covered = sum(1 for entry in entries if entry["covered"])
    passed = sum(1 for entry in entries if entry["status"] == "passed")
    failed = sum(1 for entry in entries if entry["status"] == "failed")
    missing = sum(1 for entry in entries if entry["status"] == "missing")
    coverage = round(100.0 * covered / total, 1) if total else 0.0

    return {
        "summary": {
            "total": total,
            "covered": covered,
            "coverage": coverage,
            "threshold": threshold,
            "passed": passed,
            "failed": failed,
            "missing": missing,
        },
        "requirements": entries,
    }


def write_reqcov_report(coverage: dict[str, Any], root: Path = Path(".")) -> Path:
    """Write ``build/reports/reqcov.json`` and return the written path."""
    root = Path(root)
    directory = root / _REPORT_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / _REPORT_FILE
    path.write_text(json.dumps(coverage, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
