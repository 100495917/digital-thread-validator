"""Tests for DORA and pipeline metrics collection."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from mbse import metrics

_GIT_AVAILABLE = shutil.which("git") is not None
_git_only = pytest.mark.skipif(not _GIT_AVAILABLE, reason="git is not installed")

_REPORT_DIR = Path("build") / "reports"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: object) -> None:
    _write(path, json.dumps(payload))


def _run_git(
    root: Path,
    *arguments: str,
    when: datetime | None = None,
) -> str:
    env = os.environ.copy()
    if when is not None:
        stamp = when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        env["GIT_AUTHOR_DATE"] = stamp
        env["GIT_COMMITTER_DATE"] = stamp
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return completed.stdout.strip()


def _init_repo(root: Path) -> None:
    _run_git(root, "init", "-q")
    _run_git(root, "config", "user.name", "Metrics Tester")
    _run_git(root, "config", "user.email", "metrics@example.com")
    _run_git(root, "config", "commit.gpgsign", "false")
    _run_git(root, "config", "tag.gpgSign", "false")


def _commit(root: Path, message: str, when: datetime) -> str:
    _run_git(root, "add", "-A")
    _run_git(root, "commit", "-q", "-m", message, when=when)
    return _run_git(root, "rev-parse", "HEAD")


def _tag(root: Path, name: str, when: datetime) -> None:
    _run_git(root, "tag", "-a", name, "-m", f"release {name}", when=when)


def _isolate_from_git(monkeypatch, root: Path) -> None:
    """Stop git from discovering a repository above ``root``."""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(root.parent))


def _full_metrics_shape() -> dict[str, set[str]]:
    return {
        "deployment_frequency": {"releases", "window_days", "per_week"},
        "lead_time_hours": {"median", "samples"},
        "change_failure_rate": {"failed", "total", "rate"},
        "mean_time_to_restore_hours": {"mean", "incidents"},
        "pipeline": {
            "tests_total",
            "tests_passed",
            "tests_failed",
            "flaky_tests",
            "coverage_percent",
        },
        "stages": set(),
        "source": set(),
        "status": set(),
    }


# ---------------------------------------------------------------------------
# Degraded inputs
# ---------------------------------------------------------------------------


def test_no_git_no_reports_returns_zeros(tmp_path: Path, monkeypatch) -> None:
    _isolate_from_git(monkeypatch, tmp_path)

    result = metrics.collect_metrics(tmp_path)

    assert set(result) == {
        "deployment_frequency",
        "lead_time_hours",
        "change_failure_rate",
        "mean_time_to_restore_hours",
        "pipeline",
        "stages",
        "source",
        "status",
    }
    assert result == {
        "deployment_frequency": {"releases": 0, "window_days": 30, "per_week": 0.0},
        "lead_time_hours": {"median": 0.0, "samples": 0},
        "change_failure_rate": {"failed": 0, "total": 0, "rate": 0.0},
        "mean_time_to_restore_hours": {"mean": 0.0, "incidents": 0},
        "pipeline": {
            "tests_total": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "flaky_tests": 0,
            "coverage_percent": 0.0,
        },
        "stages": [],
        "source": "git",
        "status": "partial",
    }


def test_malformed_reports_degrade_to_zeros(tmp_path: Path, monkeypatch) -> None:
    _isolate_from_git(monkeypatch, tmp_path)
    _write(tmp_path / _REPORT_DIR / "pipeline_runs.json", "{not json")
    _write(tmp_path / _REPORT_DIR / "junit.xml", "<testsuites")
    _write(tmp_path / _REPORT_DIR / "coverage.xml", "nope")

    result = metrics.collect_metrics(tmp_path)

    assert result["change_failure_rate"] == {"failed": 0, "total": 0, "rate": 0.0}
    assert result["pipeline"]["tests_total"] == 0
    assert result["pipeline"]["coverage_percent"] == 0.0


# ---------------------------------------------------------------------------
# Git-derived metrics
# ---------------------------------------------------------------------------


@_git_only
def test_tags_create_deployment_frequency_and_lead_time(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    now = datetime.now(UTC)
    first = now - timedelta(days=4)
    second = now - timedelta(days=2)

    _write(tmp_path / "src" / "app.py", "VALUE = 1\n")
    _commit(tmp_path, "feat: initial", first)
    _tag(tmp_path, "v0.1.0", first)

    _write(tmp_path / "src" / "app.py", "VALUE = 2\n")
    _commit(tmp_path, "feat: follow-up", second)
    _tag(tmp_path, "v0.2.0", now - timedelta(days=1))

    result = metrics.collect_metrics(tmp_path)

    assert result["status"] == "ok"
    assert result["deployment_frequency"] == {
        "releases": 2,
        "window_days": 30,
        "per_week": 0.47,
    }
    # Only the commit between v0.1.0 and v0.2.0 counts; tag is one day later.
    assert result["lead_time_hours"] == {"median": 24.0, "samples": 1}


@_git_only
def test_without_tags_lead_time_uses_recent_commits(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    now = datetime.now(UTC)

    _write(tmp_path / "src" / "app.py", "VALUE = 1\n")
    _commit(tmp_path, "feat: no release yet", now - timedelta(hours=2))
    _write(tmp_path / "src" / "app.py", "VALUE = 2\n")
    _commit(tmp_path, "feat: second", now - timedelta(hours=1))

    result = metrics.collect_metrics(tmp_path)

    assert result["status"] == "ok"
    assert result["deployment_frequency"]["releases"] == 0
    assert result["lead_time_hours"]["samples"] == 2
    assert 0.9 <= result["lead_time_hours"]["median"] <= 2.1


@_git_only
def test_git_repo_without_commit_does_not_crash(tmp_path: Path) -> None:
    _init_repo(tmp_path)

    result = metrics.collect_metrics(tmp_path)

    assert result["status"] == "ok"
    assert result["deployment_frequency"]["releases"] == 0
    assert result["lead_time_hours"] == {"median": 0.0, "samples": 0}


# ---------------------------------------------------------------------------
# Report-derived metrics
# ---------------------------------------------------------------------------


def test_change_failure_rate_from_pipeline_runs(tmp_path: Path, monkeypatch) -> None:
    _isolate_from_git(monkeypatch, tmp_path)
    _write_json(
        tmp_path / _REPORT_DIR / "pipeline_runs.json",
        [
            {"status": "pass"},
            {"status": "fail"},
            {"status": "fail"},
            {"status": "pass"},
            {"status": "unknown"},
            "not-an-entry",
        ],
    )

    result = metrics.collect_metrics(tmp_path)

    assert result["change_failure_rate"] == {"failed": 2, "total": 4, "rate": 0.5}


def test_mean_time_to_restore_from_incidents(tmp_path: Path, monkeypatch) -> None:
    _isolate_from_git(monkeypatch, tmp_path)
    _write_json(
        tmp_path / _REPORT_DIR / "incidents.json",
        [
            {"opened": "2026-01-01T00:00:00+00:00", "restored": "2026-01-01T04:00:00+00:00"},
            {"opened": "2026-02-01T00:00:00Z", "restored": "2026-02-01T02:00:00Z"},
            {"opened": "not-a-date", "restored": "2026-02-01T02:00:00Z"},
            {"opened": "2026-03-01T00:00:00+00:00"},
        ],
    )

    result = metrics.collect_metrics(tmp_path)

    assert result["mean_time_to_restore_hours"] == {"mean": 3.0, "incidents": 2}


def test_pipeline_statistics_from_junit_coverage_and_flaky(tmp_path: Path, monkeypatch) -> None:
    _isolate_from_git(monkeypatch, tmp_path)
    _write(
        tmp_path / _REPORT_DIR / "junit.xml",
        "\n".join(  # noqa: FLY002 - literal XML fixture is clearer than an f-string
            [
                "<testsuites>",
                '  <testsuite tests="6" failures="1" errors="0" skipped="1" />',
                '  <testsuite tests="4" failures="0" errors="1" skipped="1" />',
                "</testsuites>",
            ]
        )
        + "\n",
    )
    _write(
        tmp_path / _REPORT_DIR / "coverage.xml",
        '<coverage line-rate="0.875" lines-valid="8" lines-covered="7" />\n',
    )
    _write_json(
        tmp_path / _REPORT_DIR / "flaky.json",
        [{"test": "a"}, {"test": "b"}, {"test": "c"}],
    )

    result = metrics.collect_metrics(tmp_path)

    assert result["pipeline"] == {
        "tests_total": 10,
        "tests_passed": 6,
        "tests_failed": 2,
        "flaky_tests": 3,
        "coverage_percent": 87.5,
    }


def test_coverage_falls_back_to_line_totals(tmp_path: Path, monkeypatch) -> None:
    _isolate_from_git(monkeypatch, tmp_path)
    _write(
        tmp_path / _REPORT_DIR / "coverage.xml",
        '<coverage lines-valid="10" lines-covered="9" />\n',
    )

    result = metrics.collect_metrics(tmp_path)

    assert result["pipeline"]["coverage_percent"] == 90.0


def test_stages_are_passed_through(tmp_path: Path, monkeypatch) -> None:
    _isolate_from_git(monkeypatch, tmp_path)
    _write_json(
        tmp_path / _REPORT_DIR / "timings.json",
        [
            {"name": "lint", "duration_seconds": 3},
            {"name": "test", "duration_seconds": 12.5},
            "ignore-me",
        ],
    )

    result = metrics.collect_metrics(tmp_path)

    assert result["stages"] == [
        {"name": "lint", "duration_seconds": 3.0},
        {"name": "test", "duration_seconds": 12.5},
    ]


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def test_write_metrics_is_deterministic_and_complete(tmp_path: Path, monkeypatch) -> None:
    _isolate_from_git(monkeypatch, tmp_path)
    _write_json(tmp_path / _REPORT_DIR / "pipeline_runs.json", [{"status": "pass"}])
    _write(
        tmp_path / _REPORT_DIR / "junit.xml",
        '<testsuite tests="2" failures="0" errors="0" skipped="0" />\n',
    )

    path = metrics.write_metrics(tmp_path)
    first = path.read_bytes()
    metrics.write_metrics(tmp_path)
    second = path.read_bytes()

    assert path == tmp_path / _REPORT_DIR / "metrics.json"
    assert path.is_file()
    assert first == second
    assert first.endswith(b"\n")
    payload = json.loads(first)
    assert set(payload) == {
        "deployment_frequency",
        "lead_time_hours",
        "change_failure_rate",
        "mean_time_to_restore_hours",
        "pipeline",
        "stages",
        "source",
        "status",
    }
    for key, expected in _full_metrics_shape().items():
        if expected:
            assert set(payload[key]) == expected
    assert payload["source"] == "git"
    assert payload["pipeline"]["tests_total"] == 2
    # ``sort_keys`` keeps the on-disk key order stable.
    assert first.startswith(b'{\n  "change_failure_rate"')
