"""Tests for aggregate pipeline reporting and generated site pages."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import mbse
from mbse import reports


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_requirement(
    root: Path,
    requirement_id: str = "REQ-001",
    *,
    text: str = "The system shall satisfy the demo requirement.",
    status: str = "approved",
) -> None:
    _write(
        root / "requirements" / f"{requirement_id}.yaml",
        "\n".join(
            [
                f"id: {requirement_id}",
                'title: "Demo requirement"',
                f'text: "{text}"',
                "type: functional",
                "priority: high",
                "owner: team-demo",
                "verification: test",
                f"status: {status}",
            ]
        )
        + "\n",
    )


def _write_artifacts(root: Path) -> None:
    """Create a minimal consistent requirement/model/code/test tree."""
    _write_requirement(root)
    _write(
        root / "models" / "system.yaml",
        "\n".join(  # noqa: FLY002
            [
                "system: Demo",
                "version: 1.0.0",
                "elements:",
                "  - id: BLK-demo",
                "    kind: block",
                "    name: Demo",
                "    satisfies: [REQ-001]",
                "    allocated_to: src/demo.py",
            ]
        )
        + "\n",
    )
    _write(root / "src" / "demo.py", "# @implements REQ-001\nVALUE = 1\n")
    _write(
        root / "tests" / "test_demo.py",
        "\n".join(  # noqa: FLY002
            [
                "import pytest",
                "",
                '@pytest.mark.req("REQ-001")',
                "def test_demo_requirement():",
                "    assert True",
            ]
        )
        + "\n",
    )


def _write_junit(
    root: Path,
    *,
    tests: int = 2,
    failures: int = 0,
    errors: int = 0,
    skipped: int = 0,
) -> None:
    _write(
        root / "build" / "reports" / "junit.xml",
        (
            '<?xml version="1.0" encoding="utf-8"?>'
            f'<testsuites><testsuite tests="{tests}" failures="{failures}" '
            f'errors="{errors}" skipped="{skipped}" /></testsuites>'
        ),
    )


def _write_coverage(root: Path, rate: float = 0.9) -> None:
    _write(
        root / "build" / "reports" / "coverage.xml",
        (
            '<?xml version="1.0" ?>'
            f'<coverage line-rate="{rate}" lines-valid="10" '
            f'lines-covered="{int(rate * 10)}" />'
        ),
    )


def _write_security(
    root: Path,
    *,
    status: str = "passed",
    total: int = 1,
    by_severity: dict[str, int] | None = None,
) -> None:
    severities = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    if by_severity:
        severities.update(by_severity)
    payload = {
        "summary": {
            "status": status,
            "total": total,
            "by_severity": severities,
            "by_tool": {"bandit": total, "semgrep": 0},
            "tool_status": {"bandit": "passed", "semgrep": "unavailable"},
        },
        "results": [],
    }
    _write(root / "build" / "reports" / "security.json", json.dumps(payload))


def _write_impact(
    root: Path,
    *,
    risk: str = "high",
    counts: dict[str, int] | None = None,
) -> None:
    values = {
        "changed_files": 1,
        "directly_changed": 1,
        "impacted": 2,
        "needs_review": 1,
        "needs_retest": 2,
    }
    if counts:
        values.update(counts)
    payload = {
        "base": "origin/main",
        "head": "HEAD",
        "changed_files": ["src/demo.py"],
        "artifacts": {
            "directly_changed": [],
            "impacted": [],
            "needs_review": [],
            "needs_retest": [],
        },
        "summary": values,
        "risk": {
            "level": risk,
            "safety_requirements": 0,
            "security_requirements": 0,
            "depth": 2,
            "changed_files": values["changed_files"],
        },
        "requirements": {"direct": ["REQ-001"], "affected": ["REQ-001"]},
    }
    _write(root / "build" / "reports" / "impact.json", json.dumps(payload))


def _write_thread(root: Path) -> None:
    payload = {
        "metadata": {},
        "nodes": [
            {"id": "REQ-001", "type": "Requirement"},
            {"id": "src/demo.py", "type": "CodeModule"},
        ],
        "edges": [{"source": "src/demo.py", "target": "REQ-001", "type": "IMPLEMENTS"}],
    }
    _write(root / "digital_thread" / "thread.json", json.dumps(payload))
    _write(
        root / "build" / "reports" / "thread_diff.md",
        "\n".join(  # noqa: FLY002
            [
                "# Digital thread diff",
                "",
                "## Added nodes",
                "- REQ-002",
                "",
                "## Removed nodes",
                "- REQ-003",
                "",
                "## Modified nodes",
                "- RESULT:tests/test_demo.py::test_demo_requirement",
                "- src/demo.py",
                "",
                "## Stale nodes",
                "- none",
                "",
                "## Added edges",
                "- src/demo.py -> REQ-001",
                "",
            ]
        ),
    )


def _full_tree(root: Path, *, junit_failures: int = 0, security_status: str = "passed") -> None:
    _write_artifacts(root)
    _write_junit(root, failures=junit_failures)
    _write_coverage(root)
    _write_security(root, status=security_status)
    _write_impact(root)
    _write_thread(root)


def _install_metrics(monkeypatch, module: types.ModuleType) -> None:
    """Replace ``mbse.metrics`` so report rendering is independent of Git."""
    monkeypatch.setitem(sys.modules, "mbse.metrics", module)
    monkeypatch.setattr(mbse, "metrics", module, raising=False)


def test_build_summary_shape_and_values(tmp_path: Path) -> None:
    _full_tree(tmp_path)

    summary = reports.build_summary(tmp_path)

    assert set(summary) == {
        "status",
        "validation",
        "traceability",
        "tests",
        "coverage",
        "security",
        "impact",
        "thread",
        "metrics",
    }
    assert summary["status"] == "pass"
    assert summary["validation"] == {
        "requirements": 1,
        "errors": 0,
        "warnings": 0,
        "quality_score": 100.0,
    }
    assert summary["traceability"]["traceability_coverage"] == 100.0
    assert summary["traceability"]["verification_coverage"] == 0.0
    assert summary["tests"] == {
        "total": 2,
        "passed": 2,
        "failed": 0,
        "skipped": 0,
        "requirements_coverage": 0.0,
    }
    assert summary["coverage"] == {"percent": 90.0}
    assert summary["security"] == {
        "status": "passed",
        "total": 1,
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
        "tools": ["bandit", "semgrep"],
    }
    assert summary["impact"] == {
        "risk": "high",
        "changed_files": 1,
        "directly_changed": 1,
        "impacted": 2,
        "needs_review": 1,
        "needs_retest": 2,
    }
    assert summary["thread"] == {
        "nodes": 2,
        "edges": 1,
        "added": 1,
        "removed": 1,
        "modified": 2,
        "stale": 0,
    }
    assert set(summary["metrics"]) == {
        "deployment_frequency",
        "lead_time_hours",
        "change_failure_rate",
        "mean_time_to_restore_hours",
        "pipeline",
        "stages",
        "source",
        "status",
    }
    assert set(summary["metrics"]["pipeline"]) == {
        "tests_total",
        "tests_passed",
        "tests_failed",
        "flaky_tests",
        "coverage_percent",
    }


def test_status_fails_on_test_failure(tmp_path: Path) -> None:
    _full_tree(tmp_path, junit_failures=1)

    summary = reports.build_summary(tmp_path)

    assert summary["tests"]["failed"] == 1
    assert summary["tests"]["passed"] == 1
    assert summary["status"] == "fail"


def test_status_fails_on_validation_error(tmp_path: Path) -> None:
    _write_artifacts(tmp_path)
    _write_requirement(tmp_path, text="The system must satisfy the demo requirement.")

    summary = reports.build_summary(tmp_path)

    assert summary["validation"]["errors"] == 1
    assert summary["status"] == "fail"


def test_status_fails_on_security_gate(tmp_path: Path) -> None:
    _full_tree(tmp_path, security_status="failed")

    summary = reports.build_summary(tmp_path)

    assert summary["security"]["status"] == "failed"
    assert summary["status"] == "fail"


def test_missing_reports_degrade(tmp_path: Path) -> None:
    _write_requirement(tmp_path)

    summary = reports.build_summary(tmp_path)

    assert summary["status"] == "pass"
    assert summary["validation"]["requirements"] == 1
    assert summary["tests"] == {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "requirements_coverage": 0.0,
    }
    assert summary["coverage"] == {"percent": 0.0}
    assert summary["security"] == {
        "status": "not-run",
        "total": 0,
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
        "tools": [],
    }
    assert summary["impact"] == {"status": "not-run"}
    assert summary["thread"] == {
        "nodes": 0,
        "edges": 0,
        "added": 0,
        "removed": 0,
        "modified": 0,
        "stale": 0,
    }
    assert set(summary["metrics"]) == {
        "deployment_frequency",
        "lead_time_hours",
        "change_failure_rate",
        "mean_time_to_restore_hours",
        "pipeline",
        "stages",
        "source",
        "status",
    }
    assert summary["metrics"]["pipeline"] == {
        "tests_total": 0,
        "tests_passed": 0,
        "tests_failed": 0,
        "flaky_tests": 0,
        "coverage_percent": 0.0,
    }


def test_metrics_page_includes_dora_pipeline_and_stages(tmp_path: Path, monkeypatch) -> None:
    _full_tree(tmp_path)
    module = types.ModuleType("mbse.metrics")
    module.collect_metrics = lambda root: {
        "deployment_frequency": {"releases": 4, "window_days": 30, "per_week": 0.93},
        "lead_time_hours": {"median": 12.5, "samples": 3},
        "change_failure_rate": {"failed": 1, "total": 10, "rate": 0.1},
        "mean_time_to_restore_hours": {"mean": 2.0, "incidents": 1},
        "pipeline": {
            "tests_total": 12,
            "tests_passed": 10,
            "tests_failed": 1,
            "flaky_tests": 2,
            "coverage_percent": 88.5,
        },
        "stages": [{"name": "validate", "duration_seconds": 12.5}],
        "source": "git",
        "status": "ok",
    }
    _install_metrics(monkeypatch, module)

    result = reports.write_summary(tmp_path)

    page = (tmp_path / "docs" / "generated" / "metrics.md").read_text(encoding="utf-8")
    assert "## DORA metrics" in page
    assert "| Deployment frequency (per week) | 0.93 |" in page
    assert "| Lead time median (hours) | 12.5 |" in page
    assert "| Change failure rate | 0.1 |" in page
    assert "| Mean time to restore (hours) | 2.0 |" in page
    assert "## Pipeline metrics" in page
    assert "| Tests | 12 |" in page
    assert "| Flaky tests | 2 |" in page
    assert "| Coverage (%) | 88.5 |" in page
    assert "## Stage durations" in page
    assert "| validate | 12.5 |" in page
    assert "[metrics.json](../reports/metrics.json)" in page

    summary_md = Path(result["summary_md"]).read_text(encoding="utf-8")
    assert "| Deployment frequency (per week) | 0.93 |" in summary_md
    assert "## Stage durations" in summary_md
    assert "[metrics.json](../reports/metrics.json)" in summary_md


def test_metrics_unavailable_degrades_to_zeros(tmp_path: Path, monkeypatch) -> None:
    _full_tree(tmp_path)
    module = types.ModuleType("mbse.metrics")

    def _unavailable(root: Path) -> dict:
        raise RuntimeError("metrics unavailable")

    module.collect_metrics = _unavailable
    _install_metrics(monkeypatch, module)

    summary = reports.build_summary(tmp_path)

    assert summary["metrics"]["pipeline"] == {
        "tests_total": 0,
        "tests_passed": 0,
        "tests_failed": 0,
        "flaky_tests": 0,
        "coverage_percent": 0.0,
    }
    assert summary["metrics"]["deployment_frequency"]["per_week"] == 0.0
    assert summary["metrics"]["stages"] == []

    reports.write_summary(tmp_path)

    page = (tmp_path / "docs" / "generated" / "metrics.md").read_text(encoding="utf-8")
    assert "| Deployment frequency (per week) | 0.0 |" in page
    assert "| Tests | 0 |" in page
    assert "## Stage durations" not in page


def test_thread_diff_counts_parse_sections(tmp_path: Path) -> None:
    _write_thread(tmp_path)

    thread = reports.build_summary(tmp_path)["thread"]

    assert thread["nodes"] == 2
    assert thread["edges"] == 1
    assert thread["added"] == 1
    assert thread["removed"] == 1
    assert thread["modified"] == 2
    assert thread["stale"] == 0


def test_write_summary_pages_links_and_copies(tmp_path: Path) -> None:
    _full_tree(tmp_path)

    result = reports.write_summary(tmp_path)

    summary_json = Path(result["summary_json"])
    summary_md = Path(result["summary_md"])
    assert summary_json == tmp_path / "build" / "reports" / "summary.json"
    assert summary_md == tmp_path / "build" / "reports" / "summary.md"
    assert json.loads(summary_json.read_text(encoding="utf-8"))["status"] == "pass"

    markdown = summary_md.read_text(encoding="utf-8")
    assert "pipeline-passing-brightgreen" in markdown
    assert "../reports/junit.xml" in markdown
    assert "DORA metrics" in markdown
    assert "Pipeline metrics" in markdown
    assert "../reports/metrics.json" in markdown

    expected_pages = {
        "summary.md",
        "tests.md",
        "security.md",
        "impact.md",
        "metrics.md",
    }
    pages = {Path(path).name for path in result["site_pages"]}
    assert pages == expected_pages
    for name in expected_pages:
        page = tmp_path / "docs" / "generated" / name
        assert page.is_file()
        assert "../reports/" in page.read_text(encoding="utf-8")

    tests_page = (tmp_path / "docs" / "generated" / "tests.md").read_text(encoding="utf-8")
    assert "| Total | 2 |" in tests_page
    assert "../reports/junit.xml" in tests_page
    assert "../reports/coverage.xml" in tests_page

    security_page = (tmp_path / "docs" / "generated" / "security.md").read_text(encoding="utf-8")
    assert "passed" in security_page
    assert "../reports/security.json" in security_page

    impact_page = (tmp_path / "docs" / "generated" / "impact.md").read_text(encoding="utf-8")
    assert "high" in impact_page
    assert "../reports/impact.json" in impact_page

    metrics_page = (tmp_path / "docs" / "generated" / "metrics.md").read_text(encoding="utf-8")
    assert "Pipeline counts" in metrics_page
    assert "DORA metrics" in metrics_page
    assert "Deployment frequency (per week)" in metrics_page
    assert "Change failure rate" in metrics_page
    assert "Mean time to restore (hours)" in metrics_page
    assert "Pipeline metrics" in metrics_page
    assert "Flaky tests" in metrics_page
    assert "../reports/metrics.json" in metrics_page
    assert "../reports/summary.json" in metrics_page

    copied = {Path(path).name for path in result["reports_copied"]}
    assert {"junit.xml", "coverage.xml", "security.json", "impact.json", "summary.json"} <= copied
    assert (tmp_path / "docs" / "reports" / "junit.xml").is_file()
    assert (tmp_path / "docs" / "reports" / "summary.json").read_text(
        encoding="utf-8"
    ) == summary_json.read_text(encoding="utf-8")


def test_write_summary_badge_failing(tmp_path: Path) -> None:
    _full_tree(tmp_path, security_status="failed")

    result = reports.write_summary(tmp_path)

    markdown = Path(result["summary_md"]).read_text(encoding="utf-8")
    assert "pipeline-failing-red" in markdown
    page = (tmp_path / "docs" / "generated" / "summary.md").read_text(encoding="utf-8")
    assert "pipeline-failing-red" in page


def test_write_summary_is_deterministic(tmp_path: Path) -> None:
    _full_tree(tmp_path)

    reports.write_summary(tmp_path)
    first = {
        path.relative_to(tmp_path).as_posix(): path.read_text(encoding="utf-8")
        for directory in ("build", "docs")
        for path in sorted((tmp_path / directory).rglob("*"))
        if path.is_file()
    }
    reports.write_summary(tmp_path)
    second = {
        path.relative_to(tmp_path).as_posix(): path.read_text(encoding="utf-8")
        for directory in ("build", "docs")
        for path in sorted((tmp_path / directory).rglob("*"))
        if path.is_file()
    }

    assert first == second
