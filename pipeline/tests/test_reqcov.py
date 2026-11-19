"""Tests for requirements verification coverage and its report."""

from __future__ import annotations

import json
from pathlib import Path

from mbse.reqcov import (
    DEFAULT_THRESHOLD,
    compute_requirements_coverage,
    write_reqcov_report,
)


def _write_requirement(
    root: Path,
    requirement_id: str,
    *,
    status: str = "approved",
    requirement_type: str = "functional",
) -> None:
    lines = [
        f"id: {requirement_id}",
        f'title: "Requirement {requirement_id}"',
        'text: "The system shall satisfy the demo requirement."',
        f"type: {requirement_type}",
        "priority: high",
        "owner: team-demo",
        "verification: test",
        f"status: {status}",
        'rationale: "Keeps the demo traceable."',
    ]
    path = root / "requirements" / f"{requirement_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_results(
    root: Path,
    results: dict[str, list[dict[str, object]]],
) -> Path:
    path = root / "build" / "reports" / "req_results.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    return path


def _entry_by_id(coverage: dict[str, object], requirement_id: str) -> dict[str, object]:
    entries = coverage["requirements"]
    assert isinstance(entries, list)
    matches = [entry for entry in entries if entry["id"] == requirement_id]
    assert len(matches) == 1
    return matches[0]


def test_all_passing_requirements_are_fully_covered(tmp_path: Path) -> None:
    _write_requirement(tmp_path, "REQ-002")
    _write_requirement(tmp_path, "REQ-001")
    _write_results(
        tmp_path,
        {
            "REQ-002": [{"test": "test_two", "outcome": "passed", "duration": 0.2}],
            "REQ-001": [{"test": "test_one", "outcome": "passed", "duration": 0.1}],
        },
    )

    coverage = compute_requirements_coverage(tmp_path)

    assert coverage["summary"] == {
        "total": 2,
        "covered": 2,
        "coverage": 100.0,
        "threshold": DEFAULT_THRESHOLD,
        "passed": 2,
        "failed": 0,
        "missing": 0,
    }
    assert [entry["id"] for entry in coverage["requirements"]] == ["REQ-001", "REQ-002"]


def test_failing_requirement_reduces_coverage_and_is_listed(tmp_path: Path) -> None:
    _write_requirement(tmp_path, "REQ-001")
    _write_requirement(tmp_path, "REQ-002")
    _write_results(
        tmp_path,
        {
            "REQ-001": [{"test": "test_one", "outcome": "passed", "duration": 0.1}],
            "REQ-002": [{"test": "test_two", "outcome": "failed", "duration": 0.3}],
        },
    )

    coverage = compute_requirements_coverage(tmp_path)

    assert coverage["summary"] == {
        "total": 2,
        "covered": 1,
        "coverage": 50.0,
        "threshold": DEFAULT_THRESHOLD,
        "passed": 1,
        "failed": 1,
        "missing": 0,
    }
    failed_entry = _entry_by_id(coverage, "REQ-002")
    assert failed_entry["status"] == "failed"
    assert failed_entry["covered"] is False
    assert failed_entry["failed"] == 1
    assert failed_entry["tests"] == [{"test": "test_two", "outcome": "failed", "duration": 0.3}]


def test_missing_results_file_yields_zero_coverage(tmp_path: Path) -> None:
    _write_requirement(tmp_path, "REQ-001")
    _write_requirement(tmp_path, "REQ-002")

    coverage = compute_requirements_coverage(tmp_path)

    assert coverage["summary"] == {
        "total": 2,
        "covered": 0,
        "coverage": 0.0,
        "threshold": DEFAULT_THRESHOLD,
        "passed": 0,
        "failed": 0,
        "missing": 2,
    }
    assert all(entry["status"] == "missing" for entry in coverage["requirements"])


def test_skipped_only_requirement_is_missing(tmp_path: Path) -> None:
    _write_requirement(tmp_path, "REQ-001")
    _write_results(
        tmp_path,
        {"REQ-001": [{"test": "test_one", "outcome": "skipped", "duration": 0.0}]},
    )

    coverage = compute_requirements_coverage(tmp_path)

    assert coverage["summary"]["coverage"] == 0.0
    assert coverage["summary"]["missing"] == 1
    entry = _entry_by_id(coverage, "REQ-001")
    assert entry["status"] == "missing"
    assert entry["skipped"] == 1


def test_threshold_is_echoed_from_the_caller(tmp_path: Path) -> None:
    _write_requirement(tmp_path, "REQ-001")
    _write_results(
        tmp_path,
        {"REQ-001": [{"test": "test_one", "outcome": "failed", "duration": 0.1}]},
    )

    coverage = compute_requirements_coverage(tmp_path, threshold=75.0)

    assert coverage["summary"]["threshold"] == 75.0
    assert coverage["summary"]["coverage"] == 0.0
    assert coverage["summary"]["coverage"] < coverage["summary"]["threshold"]


def test_custom_results_path_is_used(tmp_path: Path) -> None:
    _write_requirement(tmp_path, "REQ-001")
    results_path = tmp_path / "custom" / "results.json"
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(
        json.dumps({"REQ-001": [{"test": "test_one", "outcome": "passed"}]}),
        encoding="utf-8",
    )

    coverage = compute_requirements_coverage(tmp_path, results_path=results_path)

    assert coverage["summary"]["coverage"] == 100.0
    assert coverage["summary"]["covered"] == 1


def test_report_is_written_to_build_reports_and_is_deterministic(tmp_path: Path) -> None:
    _write_requirement(tmp_path, "REQ-001")
    _write_results(
        tmp_path,
        {"REQ-001": [{"test": "test_one", "outcome": "passed", "duration": 0.1}]},
    )
    coverage = compute_requirements_coverage(tmp_path)

    path = write_reqcov_report(coverage, tmp_path)

    assert path == tmp_path / "build" / "reports" / "reqcov.json"
    assert path.is_file()
    first = path.read_text(encoding="utf-8")
    assert first.endswith("\n")
    data = json.loads(first)
    assert data == coverage
    assert data["summary"]["coverage"] == 100.0
    assert data["requirements"][0]["id"] == "REQ-001"

    write_reqcov_report(coverage, tmp_path)
    assert path.read_text(encoding="utf-8") == first


def test_only_approved_requirements_are_counted(tmp_path: Path) -> None:
    _write_requirement(tmp_path, "REQ-001")
    _write_requirement(tmp_path, "REQ-002", status="draft")
    _write_requirement(tmp_path, "REQ-003", status="deprecated")
    _write_results(
        tmp_path,
        {
            "REQ-001": [{"test": "test_one", "outcome": "passed", "duration": 0.1}],
            "REQ-002": [{"test": "test_two", "outcome": "passed", "duration": 0.1}],
            "REQ-003": [{"test": "test_three", "outcome": "passed", "duration": 0.1}],
        },
    )

    coverage = compute_requirements_coverage(tmp_path)

    assert coverage["summary"]["total"] == 1
    assert coverage["summary"]["coverage"] == 100.0
    assert [entry["id"] for entry in coverage["requirements"]] == ["REQ-001"]


def test_empty_approved_set_has_zero_coverage(tmp_path: Path) -> None:
    (tmp_path / "requirements").mkdir(parents=True, exist_ok=True)

    coverage = compute_requirements_coverage(tmp_path)

    assert coverage == {
        "summary": {
            "total": 0,
            "covered": 0,
            "coverage": 0.0,
            "threshold": DEFAULT_THRESHOLD,
            "passed": 0,
            "failed": 0,
            "missing": 0,
        },
        "requirements": [],
    }
